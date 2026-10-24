"""录音状态浮窗:屏幕底部居中的玻璃胶囊(macOS 26 用 Liquid Glass,旧系统回退到毛玻璃)。

所有方法都必须在主线程调用(其他线程用 PyObjCTools.AppHelper.callAfter)。
"""
import math
import time

import objc
from AppKit import (
    NSAnimationContext,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSFontWeightMedium,
    NSImage,
    NSImageSymbolConfiguration,
    NSImageView,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSObject,
    NSPanel,
    NSScreen,
    NSStatusBar,
    NSStatusWindowLevel,
    NSTimer,
    NSURL,
    NSVariableStatusItemLength,
    NSView,
    NSVisualEffectView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSWorkspace,
)

CAPSULE_W, CAPSULE_H = 132, 44
MARGIN = 24               # 胶囊四周留给阴影的透明边
BOTTOM_GAP = 28           # 胶囊离 Dock 上沿的距离
N_BARS, BAR_W, BAR_GAP = 11, 3, 3
BAR_MIN, BAR_MAX = 3, 22


class LevelView(NSView):
    """录音时显示滚动的音量条,识别时显示一道行进的波纹。"""

    def initWithFrame_(self, frame):
        self = objc.super(LevelView, self).initWithFrame_(frame)
        if self is not None:
            self.levels = [0.0] * N_BARS
            self.mode = "recording"
        return self

    def push_(self, level):
        self.levels = self.levels[1:] + [level]
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        h = self.bounds().size.height
        if self.mode == "recording":
            heights = [BAR_MIN + (BAR_MAX - BAR_MIN) * v for v in self.levels]
            NSColor.labelColor().set()
        else:
            t = time.time() * 6
            heights = [
                BAR_MIN + (BAR_MAX * 0.45 - BAR_MIN) * (0.5 + 0.5 * math.sin(t - i * 0.7))
                for i in range(N_BARS)
            ]
            NSColor.secondaryLabelColor().set()
        for i, bar_h in enumerate(heights):
            x = i * (BAR_W + BAR_GAP)
            r = NSMakeRect(x, (h - bar_h) / 2, BAR_W, bar_h)
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, BAR_W / 2, BAR_W / 2).fill()


class Overlay:
    def __init__(self, level_source):
        """level_source: 无参函数,返回当前音量 0~1。"""
        self.level_source = level_source
        self.timer = None
        self.generation = 0

        w, h = CAPSULE_W + 2 * MARGIN, CAPSULE_H + 2 * MARGIN
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, w, h),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        p = self.panel
        p.setOpaque_(False)
        p.setBackgroundColor_(NSColor.clearColor())
        p.setHasShadow_(False)
        p.setLevel_(NSStatusWindowLevel)
        p.setIgnoresMouseEvents_(True)
        p.setHidesOnDeactivate_(False)
        p.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorStationary
        )
        p.setAlphaValue_(0.0)

        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, CAPSULE_W, CAPSULE_H))

        icon_size = 20
        self.icon = NSImageView.alloc().initWithFrame_(
            NSMakeRect(18, (CAPSULE_H - icon_size) / 2, icon_size, icon_size)
        )
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_("mic.fill", None)
        cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(15, NSFontWeightMedium)
        self.icon.setImage_(image.imageWithSymbolConfiguration_(cfg))
        content.addSubview_(self.icon)

        bars_w = N_BARS * BAR_W + (N_BARS - 1) * BAR_GAP
        self.bars = LevelView.alloc().initWithFrame_(
            NSMakeRect(CAPSULE_W - 18 - bars_w, (CAPSULE_H - BAR_MAX) / 2, bars_w, BAR_MAX)
        )
        content.addSubview_(self.bars)

        capsule_frame = NSMakeRect(MARGIN, MARGIN, CAPSULE_W, CAPSULE_H)
        try:
            glass_cls = objc.lookUpClass("NSGlassEffectView")  # macOS 26+
            capsule = glass_cls.alloc().initWithFrame_(capsule_frame)
            capsule.setCornerRadius_(CAPSULE_H / 2)
            capsule.setContentView_(content)
        except objc.nosuchclass_error:
            capsule = NSVisualEffectView.alloc().initWithFrame_(capsule_frame)
            capsule.setMaterial_(13)      # HUDWindow
            capsule.setBlendingMode_(0)   # BehindWindow
            capsule.setState_(1)          # Active
            capsule.setWantsLayer_(True)
            capsule.layer().setCornerRadius_(CAPSULE_H / 2)
            capsule.layer().setMasksToBounds_(True)
            capsule.addSubview_(content)
            p.setHasShadow_(True)
        p.contentView().addSubview_(capsule)

    # ---- 状态切换 ----
    def show_recording(self):
        self.generation += 1
        self.bars.levels = [0.0] * N_BARS
        self.bars.mode = "recording"
        self.icon.setContentTintColor_(NSColor.systemRedColor())
        self._place()
        self.panel.orderFrontRegardless()
        self._fade(1.0, 0.16)
        self._start_timer()

    def show_transcribing(self):
        self.bars.mode = "transcribing"
        self.icon.setContentTintColor_(NSColor.secondaryLabelColor())
        self.bars.setNeedsDisplay_(True)

    def hide(self):
        self.generation += 1
        gen = self.generation

        def done():
            if gen == self.generation:   # 淡出期间没有再次按下
                self._stop_timer()
                self.panel.orderOut_(None)

        self._fade(0.0, 0.22, done)

    # ---- 内部 ----
    def _place(self):
        screen = NSScreen.mainScreen() or NSScreen.screens()[0]
        vf = screen.visibleFrame()
        size = self.panel.frame().size
        x = vf.origin.x + (vf.size.width - size.width) / 2
        y = vf.origin.y + BOTTOM_GAP - MARGIN
        self.panel.setFrameOrigin_((x, y))

    def _fade(self, alpha, duration, completion=None):
        def group(ctx):
            ctx.setDuration_(duration)
            self.panel.animator().setAlphaValue_(alpha)

        NSAnimationContext.runAnimationGroup_completionHandler_(group, completion)

    def _start_timer(self):
        if self.timer is None:
            self.timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
                1 / 30, True, lambda _t: self._tick()
            )

    def _stop_timer(self):
        if self.timer is not None:
            self.timer.invalidate()
            self.timer = None

    def _tick(self):
        if self.bars.mode == "recording":
            self.bars.push_(self.level_source())
        else:
            self.bars.setNeedsDisplay_(True)


class _MenuTarget(NSObject):
    def openReplace_(self, sender):
        NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(str(self.base / "replace.txt")))

    def openFolder_(self, sender):
        NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(str(self.base)))


class StatusMenu:
    """菜单栏图标: 显示状态,提供编辑热词表和退出。"""

    def __init__(self, base):
        self.target = _MenuTarget.alloc().init()
        self.target.base = base
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_("mic", "语音输入")
        image.setTemplate_(True)
        self.item.button().setImage_(image)

        menu = NSMenu.alloc().init()
        self.status = menu.addItemWithTitle_action_keyEquivalent_("", None, "")
        self.status.setEnabled_(False)
        menu.addItem_(NSMenuItem.separatorItem())
        for title, action in (("编辑热词表…", "openReplace:"), ("打开程序文件夹", "openFolder:")):
            menu.addItemWithTitle_action_keyEquivalent_(title, action, "").setTarget_(self.target)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItemWithTitle_action_keyEquivalent_("退出语音输入", "terminate:", "q")
        self.item.setMenu_(menu)

    def set_status(self, text):
        self.status.setTitle_(text)


if __name__ == "__main__":
    # 演示: 录音 2.5s → 识别 1.5s → 消失
    import random
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
    from PyObjCTools import AppHelper

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    ov = Overlay(lambda: random.random() ** 1.5)
    ov.show_recording()
    AppHelper.callLater(2.5, ov.show_transcribing)
    AppHelper.callLater(4.0, ov.hide)
    AppHelper.callLater(4.6, AppHelper.stopEventLoop)
    AppHelper.runEventLoop()
