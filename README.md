# 从 apt 源制作 UEFI 可启动的 loong64 最小系统

本教程记录如何用 **ULoong 软件源的用户态** + **本机已有的 loongarch64 内核**，
做一个能通过 UEFI 启动、进入 root shell 的最小系统。全过程不需要 root 权限，
也不需要为目标机分区或安装引导器到磁盘。

最终产物是一个 FAT32 镜像：

```
EFI/BOOT/BOOTLOONGARCH64.EFI   GRUB（UEFI fallback 路径，固件自动识别）
EFI/BOOT/grub.cfg              启动菜单
boot-assets/vmlinuz            loongarch64 内核（EFI zboot Image）
boot-assets/initrd.img         initramfs，内含完整最小 rootfs
```

## 适用范围

- 目标：loongarch64 设备，固件支持 UEFI（多数新板卡/虚拟机满足）。
- 用户态：ULoong Resolute 26.04（`https://uloong.loongfans.cn/uloong/`），
  对应 Ubuntu 26.04 loong64，约 1.8 万个 `main` 包。
- 内核：**自带**。ULoong 源里没有 `linux-image-*` 二进制内核，只有源码与头文件；
  本教程直接使用目标机/构建机上已经能启动的内核及其模块。
- 形态：rootfs 全部驻留内存（initramfs），适合最小验证、救援、演示。
  重启后改动丢失；要持久化需要另做带 ext4 根分区的镜像。

## 为什么可行

1. **内核与用户态的 ABI 是稳定的**。内核版本比用户态更新不会破坏基础命令；
   实测 ULoong 的 bash（链接 glibc 2.43）可直接在 7.1.x 内核 + glibc 2.44 主机上运行。
2. **页大小要匹配**。示例内核是 16K 页（`CONFIG_PAGE_SIZE_16KB`）；ULoong 二进制的
   ELF 段对齐是 64K，是 16K 的整数倍，所以能正常加载。若自己编内核，请确认
   `PAGE_SIZE` 与用户态工具链的 `-z max-page-size` 兼容。
3. **UEFI fallback 启动**。固件在没有 NVRAM 启动项时会扫描 FAT 分区上的
   `\EFI\BOOT\BOOTLOONGARCH64.EFI`，因此镜像写进 U 盘即可被识别，无需注册启动项。

## 前置条件

构建机（可以是任意 loongarch64 机器，但需能运行目标用户态的二进制）：

```sh
# 需要的工具
sudo apt install cpio gzip mtools dpkg-deb qemu-system-loongarch64 ovmf  # 名称按发行版调整
```

另外需要三样输入：

1. 一个可用的 loongarch64 内核 `vmlinuz`（EFI zboot Image）和同版本 modules 目录；
2. `BOOTLOONGARCH64.EFI`（GRUB 的 loong64 EFI 应用）；
3. 本仓库的 `scripts/` 与 `assets/`。

> 如果没有现成的 GRUB EFI 应用，可从 loong64 的 `grub-efi-loong64` 包生成：
>
> ```sh
> grub-mkimage -O loongarch64-efi -o BOOTLOONGARCH64.EFI \
>   -p /EFI/BOOT -d /usr/lib/grub/loongarch64-efi \
>   fat iso9660 part_gpt part_msdos normal boot linux configfile search search_fs_file
> ```

## 步骤 1：准备目录

```sh
export WORK=~/work/loong64-minimal
mkdir -p "$WORK"
git clone <this-repo> "$WORK/guide"
cd "$WORK/guide"
```

下面所有相对路径都以仓库根目录为基准。

## 步骤 2：解出最小 rootfs

`scripts/build-rootfs.py` 从 apt 源下载索引，算出一组基础包的依赖闭包，
用 `dpkg-deb --fsys-tarfile` + `tar` 直接解包。**不运行 maintainer scripts**，
因此不需要 chroot/root。

```sh
python3 scripts/build-rootfs.py --workdir "$WORK" --extra "nano,less"
```

产出：

- `$WORK/rootfs/` —— 最小 rootfs
- `$WORK/Packages` —— 包索引（便于自查）
- `$WORK/debs/` —— 下载缓存

脚本会自动把 `assets/etc/` 下的 `passwd`、`group`、`shadow`、`hostname`、
`hosts` 复制进 rootfs，并生成一个最小的 `var/lib/dpkg/status`，使 `dpkg -l` 可用。

> 想加包只需 `--extra "pkg1,pkg2"`，或改动脚本顶部的 `BASE` 列表。
> 注意：解包方式不会触发 postinst，少数需要脚本初始化的服务（如 systemd）
> 不能指望直接可用；本教程的 init 只启动 shell。

## 步骤 3：确认内核与模块

```sh
export KVER="$(uname -r)"          # 或你准备好的内核版本
ls /boot/vmlinuz-$KVER
ls /lib/modules/$KVER/kernel/drivers/virtio/
```

`scripts/make-initrd.sh` 会把需要的 virtio 模块拷进 rootfs，并把 `assets/init`
里的 `__KVER__` 替换成实际版本。如果你的硬件不需要 virtio，可跳过或按实际改模块列表。

## 步骤 4：打包 initramfs

```sh
KVER="$KVER" MODULE_DIR=/lib/modules/$KVER/kernel \
  scripts/make-initrd.sh "$WORK/rootfs" "$WORK/initrd.img"
```

关键点：

- `/init` 挂载 `proc`、`sys`、`devtmpfs`、`run`，加载模块，最后 `exec /bin/sh`。
- **不要**在 `/init` 里 `exec </dev/console`。PID 1 已从内核继承 console 作为
  stdio，显式打开 `/dev/console` 会让 shell 失去 tty、串口输入丢失。
- cpio 用 `-R 0:0` 让归档内所有文件归 root:root；内核解包 initramfs 时保留该属主，
  因此系统内 `id` 返回 `uid=0(root)`，文件属主也正确。

## 步骤 5：生成 UEFI 镜像

```sh
SIZE=192M scripts/make-uefi-image.sh \
  "$WORK/minimal-uefi.img" \
  /boot/vmlinuz-$KVER \
  "$WORK/initrd.img" \
  /path/to/BOOTLOONGARCH64.EFI
```

脚本用 `truncate` + `mtools` 建 FAT32，无需 root、无需 loop 设备。
`assets/grub.cfg` 会以 `search --file /boot-assets/vmlinuz` 找到镜像所在分区，
把内核和 initrd 交给它。

## 步骤 6：验证与部署

QEMU（需要 loongarch64 版 UEFI 固件，常见路径为
`/usr/share/qemu/edk2-loongarch64-code.fd`）：

```sh
scripts/verify-qemu.sh "$WORK/minimal-uefi.img"
```

预期能看到 GRUB 菜单、内核启动日志，然后进入：

```
=== loong64 minimal system :: kernel <版本> ===
Minimal system ready (rootfs in RAM).
loong64-minimal:/# id
uid=0(root) gid=0(root) groups=0(root)
loong64-minimal:/# uname -m
loongarch64
```

写入 U 盘在真机启动（**会清空目标盘**）：

```sh
sudo dd if="$WORK/minimal-uefi.img" of=/dev/sdX bs=4M status=progress conv=fsync
```

开机选择 U 盘的 UEFI 启动项即可；内核命令行已带 `console=ttyS0,115200`，串口可用。

## 脚本速查

| 脚本 | 作用 |
|---|---|
| `scripts/build-rootfs.py` | 从 apt 源解出最小 rootfs（无需 root） |
| `scripts/make-initrd.sh` | 装模块与 `/init`，打包 root:root 的 gzip cpio |
| `scripts/make-uefi-image.sh` | 用 mtools 生成 FAT32 EFI 镜像 |
| `scripts/verify-qemu.sh` | 用 QEMU + edk2 loongarch64 固件启动验证 |
| `assets/init` | PID 1 脚本（`__KVER__` 由脚本替换） |
| `assets/grub.cfg` | GRUB 菜单 |
| `assets/etc/*` | 由 maintainer scripts 负责、此处手工补的配置 |

## 限制与排错

- **非持久化**：rootfs 在内存里。要持久化请用 debootstrap 装到真实分区，
  或做一个带 GPT + ext4 根分区的镜像（需要能在 chroot 内跑维护脚本的权限）。
- **内核来源**：ULoong 源没有二进制内核；可用发行版自带内核，或取
  `linux-source-7.0.0` + loong64 headers 自行编译。PMON 直接加载通常需要未压缩
  `vmlinux`，本教程的 zboot Image 走 UEFI/GRUB。
- **`grub.cfg` 串口告警**：若 GRUB EFI 应用未编入 serial 模块，删掉 `serial` 相关
  行即可，不影响启动。
- **输入丢失**：如果 shell 收不到键盘输入，检查 `/init` 是否重定向了 stdin。
- **页大小不匹配**：若二进制无法执行并报格式错误，确认内核 `PAGE_SIZE` 与
  用户态 ELF 对齐兼容（16K 内核配 64K 对齐二进制可行）。

## 参考

- ULoong 源：<https://uloong.loongfans.cn/uloong/>
- Ubuntu 26.04 (resolute) loong64 用户态
- GRUB `loongarch64-efi` 目标、EDK2 LoongArch 固件
