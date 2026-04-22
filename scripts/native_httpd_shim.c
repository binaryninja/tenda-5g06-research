typedef unsigned long size_t;

#define AF_INET 2
#define SYS_BIND_AARCH64 200

struct sockaddr_in_compat {
    unsigned short sin_family;
    unsigned short sin_port;
    unsigned int sin_addr;
    unsigned char sin_zero[8];
};

static void copy_cstr(char *dst, size_t len, const char *src)
{
    size_t i = 0;

    if (!dst || !len) {
        return;
    }

    while (i + 1 < len && src[i]) {
        dst[i] = src[i];
        i++;
    }
    dst[i] = '\0';
}

static long raw_syscall3(long nr, long a0, long a1, long a2)
{
    register long x0 __asm__("x0") = a0;
    register long x1 __asm__("x1") = a1;
    register long x2 __asm__("x2") = a2;
    register long x8 __asm__("x8") = nr;

    __asm__ volatile("svc #0"
                     : "+r"(x0)
                     : "r"(x1), "r"(x2), "r"(x8)
                     : "memory");
    return x0;
}

__attribute__((visibility("default")))
int td_common_get_interface_ip(void *ctx, const char *ifname, char *ip, size_t len)
{
    (void)ctx;
    (void)ifname;

    copy_cstr(ip, len, "192.168.0.1");
    return 0;
}

__attribute__((visibility("default")))
int td_common_get_current_network_status(void)
{
    return 1;
}

__attribute__((visibility("default")))
int bind(int fd, const void *addr, unsigned int len)
{
    unsigned char storage[32];
    const void *use_addr = addr;
    unsigned int i;

    if (addr && len >= sizeof(struct sockaddr_in_compat) && len <= sizeof(storage)) {
        const struct sockaddr_in_compat *in = (const struct sockaddr_in_compat *)addr;

        if (in->sin_family == AF_INET) {
            for (i = 0; i < len; i++) {
                storage[i] = ((const unsigned char *)addr)[i];
            }
            ((struct sockaddr_in_compat *)storage)->sin_addr = 0;
            use_addr = storage;
        }
    }

    return (int)raw_syscall3(SYS_BIND_AARCH64, fd, (long)use_addr, len);
}
