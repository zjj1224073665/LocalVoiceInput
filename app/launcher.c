// LocalVoiceInput.app 的启动器: 在后台(无终端窗口)运行 voice_input.py。
// 有了这个 App 外壳,麦克风/输入监控/辅助功能权限就记在 LocalVoiceInput 名下。
#include <fcntl.h>
#include <libgen.h>
#include <mach-o/dyld.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
static pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

int main(void) {
    char exe[4096], real[4096];
    uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0 || !realpath(exe, real)) return 1;

    // real = <项目目录>/LocalVoiceInput.app/Contents/MacOS/LocalVoiceInput
    char *dir = real;
    for (int i = 0; i < 4; i++) dir = dirname(dir);
    char project[4096];
    strlcpy(project, dir, sizeof(project));
    if (chdir(project) != 0) return 1;

    char log_path[4096];
    snprintf(log_path, sizeof(log_path), "%s/Library/Logs/LocalVoiceInput.log", getenv("HOME"));
    int fd = open(log_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd >= 0) {
        dup2(fd, 1);
        dup2(fd, 2);
        close(fd);
    }

    char *argv[] = {".venv/bin/python", "-u", "voice_input.py", NULL};
    if (posix_spawn(&child, argv[0], NULL, NULL, argv, environ) != 0) {
        perror("posix_spawn");
        return 1;
    }
    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);

    int status = 0;
    while (waitpid(child, &status, 0) < 0) {}
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
