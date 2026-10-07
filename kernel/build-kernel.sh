#!/bin/ash
# Recipe used to build kernel/bzImage-ldac-lean from microsoft/WSL2-Linux-Kernel tag linux-msft-wsl-6.6.114.1
# (Alpine 3.20 build distro; start from the original kernel config in /proc/config.gz). Build: make -j$(nproc) bzImage
set -e
cd /build/WSL2-Linux-Kernel-linux-msft-wsl-6.6.114.1
zcat /proc/config.gz > .config
C=scripts/config
# Identify the build
$C --set-str LOCALVERSION "-ldac" --disable LOCALVERSION_AUTO
# Bluetooth + USB/IP built in (no modules needed)
$C --enable USB_SUPPORT --enable USB --enable USBIP_CORE --enable USBIP_VHCI_HCD \
   --enable BT --enable BT_BREDR --enable BT_HCIBTUSB --enable BT_HCIBTUSB_BCM --enable BT_HCIBTUSB_RTL \
   --enable BT_HCIBTUSB_MTK --enable BT_INTEL --enable BT_BCM --enable BT_RTL --enable BT_MTK --enable INPUT_UINPUT
make olddefconfig >/dev/null
# Every remaining module is unused: turn them off BEFORE disabling module support
# (with MODULES=n, Kconfig would otherwise promote all "m" options to built-in)
sed -i -E 's/^(CONFIG_[A-Za-z0-9_]+)=m$/# \1 is not set/' .config
make olddefconfig >/dev/null
$C --disable MODULES
# GPU / display (guiApplications=false)
$C --disable DRM --disable DXGKRNL --disable FB
# Security modules and audit (no policy is loaded in this VM)
$C --disable SECURITY_SELINUX --disable SECURITY_APPARMOR --disable SECURITY_SMACK --disable SECURITY_TOMOYO --disable AUDIT
# Filesystems / storage not used by WSL here
$C --disable XFS_FS --disable SQUASHFS --disable MD --disable BLK_DEV_DM
# Packet filtering (WSL NAT is done on the Windows side)
$C --disable NETFILTER
# Tracing / debugging
$C --disable FTRACE --disable KPROBES --disable KALLSYMS_ALL --disable SLUB_DEBUG --disable PROFILING \
   --disable DEBUG_INFO --enable DEBUG_INFO_NONE --disable DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT --disable DEBUG_INFO_BTF \
   --disable DEBUG_KERNEL --disable IKHEADERS
# Topology sized for a small VM
$C --disable NUMA --disable MAXSMP --disable CPUMASK_OFFSTACK --set-val NR_CPUS 64
# Running VMs inside this VM
$C --disable VIRTUALIZATION --disable KVM
make olddefconfig >/dev/null
echo "built-in: $(grep -c '=y$' .config)  modules: $(grep -c '=m$' .config)"
for k in MODULES BT BT_HCIBTUSB BT_INTEL USBIP_VHCI_HCD USB HYPERV HYPERV_NET HYPERV_STORAGE HYPERV_VSOCKETS HYPERV_BALLOON HYPERV_UTILS 9P_FS NET_9P VIRTIO_FS OVERLAY_FS FUSE_FS EXT4_FS DRM NETFILTER SECURITY_SELINUX NR_CPUS NUMA FTRACE DEBUG_INFO_NONE FW_LOADER INPUT_UINPUT SECCOMP BPF_SYSCALL CGROUPS DAX IPV6 VSOCKETS TMPFS UNIX PACKET BLK_DEV_SD SCSI HID; do printf "%s=%s  " $k "$(grep -E "^CONFIG_$k=" .config | cut -d= -f2)"; done; echo
