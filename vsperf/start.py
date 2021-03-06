#!/usr/bin/env python3

import os
import contextlib
import sys
import pprint
import base64
import time
import platform as pl
import shutil as sh
import subprocess as sp
from envbash import load_envbash
from plumbum import local
from functools import wraps
from bash import bash
import tools
import xmltool
from tee import StderrTee as errtee , StdoutTee as outtee
import xml.etree.ElementTree as xml

def get_env(var_name):
    return os.environ.get(var_name)

case_path = get_env("CASE_PATH")
system_version_id = int(get_env("SYSTEM_VERSION_ID"))
my_tool = tools.Tools()
xml_tool = xmltool.XmlTool()
work_pipe = get_env("work_pipe")
notify_pipe = get_env("notify_pipe")
# print(work_pipe)
# print(notify_pipe)

def set_check(ret):
    def my_wrap(f):
        @wraps(f)
        def log_f_as_called(*args, **kwargs):
            #cur_time = time.asctime()
            my_command = f'{f.__name__} {args} {kwargs}'
            cmd = f""":: [  BEGIN   ] :: Running '{my_command}'"""
            log(cmd)
            value = f(*args, **kwargs)
            #cur_time = time.asctime()
            cmd = f""":: [  END   ] :: Running '{my_command}' RETURN {value}"""
            log(cmd)
            return value
        return log_f_as_called
    return my_wrap    

def send_command(cmd):
    cmd = cmd + os.linesep
    # import ripdb
    # ripdb.set_trace()
    try:
        with open(notify_pipe,"r") as rfd:
            rfd.read()
            with open(work_pipe,"w") as fd:
                fd.write(cmd)
                fd.flush()
    except IOError as e:
        print("*"*80)
        print("error find")
        print(cmd)
        print(e)
        print("*"*80)
    pass

def send_all_command(cmds):
    cmd_list = str(cmds).split(os.linesep)
    for cmd in cmd_list:
        send_command(cmd)
    pass

def log(str_log):
    logs = str(str_log).split(os.linesep)
    for cmd in logs:
        cmd = f""" rlLog "{cmd}" """
        send_command(cmd)


def sh_run(cmd, str_ret_val="0"):
    cmd = """ rlRun  "{}" "{}" """.format(cmd, str_ret_val)
    send_command(cmd)
    pass

def sh_run_log(cmd, str_ret_val="0"):
    cmd = """ rlRun -l "{}" "{}" """.format(cmd, str_ret_val)
    send_command(cmd)
    pass

def run(cmd, str_ret_val="0"):
    cmds = cmd.split(os.linesep)
    cmds = [ i.strip() for i in cmds ]
    for cmd in cmds:
        if len(cmd) > 0:
            sh_run(cmd, str_ret_val)
        else:
            sh_run("echo")
    pass

def runlog(cmd, str_ret_val="0"):
    cmds = cmd.split(os.linesep)
    cmds = [ i.strip() for i in cmds ]
    for cmd in cmds:
        if len(cmd) > 0:
            sh_run_log(cmd, str_ret_val)
        else:
            sh_run("echo")
    pass
    
def log_and_run(cmd, str_ret_val="0"):
    log(cmd)
    run(cmd,str_ret_val)
    pass

def shpushd(path):
    #cmd = f"""rlRun "pushd {path}" """
    log(f"Enter dir: {path}")
    cmd = f"""pushd {path} > /dev/null"""
    send_command(cmd)
    pass


def shpopd():
    #cmd = "rlRun popd"
    cmd = "popd > /dev/null"
    send_command(cmd)
    pass

@contextlib.contextmanager
def pushd(path):
    shpushd(path)
    try:
        yield
    finally:
        shpopd()

@contextlib.contextmanager
def enter_phase(str):
    cmd = f""" rlPhaseStartTest '{str}' """
    send_command(cmd)
    time.sleep(3)
    try:
        yield
    finally:
        send_command("rlPhaseEnd")
        time.sleep(3)

###############################################################################################
###############################################################################################
###############################################################################################
###############################################################################################


def check_install(pkg_name):
    run("rpm -q {} || yum -y install {}".format(pkg_name, pkg_name))
    pass

@set_check(1)
def get_nic_name_from_mac(mac_addr):
    return my_tool.get_nic_name_from_mac(mac_addr)

@set_check(1)
def get_pmd_masks(str_cpus):
    return my_tool.get_pmd_masks(str_cpus)


@set_check(1)
def get_isolate_cpus(nic_name):
    return my_tool.get_isolate_cpus_with_nic(nic_name)

@set_check(0)
def enable_dpdk(nic1_mac, nic2_mac):
    nic1_name = get_nic_name_from_mac(nic1_mac)
    nic2_name = get_nic_name_from_mac(nic2_mac)
    nic1_businfo = my_tool.get_bus_from_name(nic1_name)
    nic2_businfo = my_tool.get_bus_from_name(nic2_name)
    cmd = """
    modprobe -r vfio-pci
    modprobe -r vfio
    modprobe vfio-pci
    modprobe vfio
    """
    log_and_run(cmd,"0,1")
    import ethtool
    driver_name = ethtool.get_module(nic1_name)
    if driver_name == "mlx5_core":
        log("This Driver is Mallenox , So just return 0")
        return 0
    if os.path.exists("/usr/share/dpdk/usertools/dpdk-devbind.py"):
        log("using dpdk-devbind.py set the vfio-pci driver to nic")
        cmd = f"""
        /usr/share/dpdk/usertools/dpdk-devbind.py -b vfio-pci {nic1_businfo}
        /usr/share/dpdk/usertools/dpdk-devbind.py -b vfio-pci {nic2_businfo}
        /usr/share/dpdk/usertools/dpdk-devbind.py --status
        """
        log_and_run(cmd)
    else:
        log("using driverctl set the vfio-pci driver to nic")
        cmd = f"""
        driverctl -v set-override {nic1_businfo} vfio-pci
        sleep 3
        driverctl -v set-override {nic2_businfo} vfio-pci
        sleep 3
        driverctl -v list-devices | grep vfio-pci
        """
        log_and_run(cmd)
    return 0

@set_check(0)
def clear_hugepage():
    hugepage_dir = bash("mount -l | grep hugetlbfs | awk '{print $3}'").value()
    log_and_run(f"rm -rf {hugepage_dir}/*")
    return 0

#################################################################################
#################################################################################
#################################################################################
#################################################################################


def os_check():
    log("Begin OS Check Now")
    import getpass
    if get_env("ID") != 'rhel':
        log("system distro not correct")
        return 1
    if getpass.getuser() != "root":
        log("User check ,must be logged in as root")
        return 1
    check_install("lrzip")
    return 0


def log_folder_check():
    log("Create log folder Now")

    log_folder = "/root/RHEL_NIC_QUAL_LOGS"

    if not os.path.exists(log_folder):
        os.mkdir(log_folder)

    time_stamp = time.strftime("%Y-%m-%d-%H-%M-%S")

    nic_log_folder = log_folder + "/" + time_stamp

    if os.path.exists(nic_log_folder):
        os.rmdir(nic_log_folder)
        os.mkdir(nic_log_folder)
    else:
        os.mkdir(nic_log_folder)

    local.path(nic_log_folder + "/vsperf_log_folder.txt").write(nic_log_folder)

    os.environ["NIC_LOG_FOLDER"] = nic_log_folder

    log(f"log folder is {nic_log_folder}")

    return 0


def conf_checks():
    proc_cmdline_info = local.path("/proc/cmdline").read()
    log(proc_cmdline_info)
    if not "intel_iommu=on" in proc_cmdline_info:
        log("Iommu Enablement" "Please enable IOMMU mode in your grub config")
        return 1
    else:
        log("Check intel_iommu=on SUCCESS")

    if bash("tuned-adm active | grep cpu-partitioning").value() == '':
        log("Tuned-adm cpu-partitioning profile must be active")
        return 1
    else:
        log("tuned-adm active OK")

    if bash(""" cat /proc/cmdline  | grep "nohz_full=[0-9]"  """).value() == '':
        log("Tuned Config Must set cores to isolate in tuned-adm profile")
        return 1
    else:
        log("nohz_full flag check is OK")
    return 0


def hugepage_checks():
    log("*** Checking Hugepage Config ***")
    ret = bash("""cat /proc/meminfo | awk /Hugepagesize/ | awk /1048576/""").value()
    if ret:
        log("Hugepage Check OK")
    else:
        log("Hugepage Check Failed" "Please enable 1G Hugepages")
        return 1
    return 0


def check_env_var(str_name):
    if get_env(str_name) != None:
        return True
    else:
        return False


def config_file_checks():
    log("*** Checking Config File ***")
    with pushd(case_path):
        str_all_name = """
        NIC1
        NIC2
        PMD_CPU_1
        PMD_CPU_2
        PMD_CPU_3
        PMD_CPU_4
        VCPU1
        VCPU2
        VCPU3
        VCPU4
        VCPU5
        TRAFFICGEN_TREX_HOST_IP_ADDR
        TRAFFICGEN_TREX_PORT1
        TRAFFICGEN_TREX_PORT2
        """.split()
        for name in str_all_name:
            if False == check_env_var(name):
                log(f"Please set the config Var {name} in Perf-Verify.conf file")
                return 1
        return 0


def nic_card_check():
    log("Now Checking for NIC cards")
    nic1 = get_env("NIC1")
    nic2 = get_env("NIC2")
    if local.path("/sys/class/net/" + nic1).exists == False or local.path("/sys/class/net/" + nic2).exists == False:
        log("NIC $NIC1 or NIC $NIC2 cannot be seen by kernel")
        return 1
    return 0


def rpm_check():
    log("*** Checking for installed RPMS ***")

    if bash("rpm -qa | grep ^openvswitch-[0-9]").value() == "":
        log("Openvswitch rpm" "Please install Openvswitch rpm")
        return 1
    else:
        log("Openvswitch rpm check OK")

    if bash("rpm -qa | grep dpdk-tools").value() == "":
        log("Please install dpdk tools rpm ")
        return 1
    else:
        log("dpdk tools check OK ")

    if bash("rpm -qa | grep dpdk-[0-9]").value() == "":
        log("Please install dpdk package rpm ")
        return 1
    else:
        log("dpdk package check OK")

    if bash("rpm -qa | grep qemu-kvm-tools").value() == "":
        log("Please install qemu-kvm-tools rpm ")
        return 1
    else:
        log("qemu-kvm-tools check OK")

    if bash("rpm -qa | grep qemu-img").value() == "":
        log("Please install qemu-img rpm ")
        return 1
    else:
        log("qemu-img package check OK")

    if bash("rpm -qa | grep qemu-kvm").value() == "":
        log("Please install qemu-kmv rpm ")
        return 1
    else:
        log("qemu-kvm package check OK")

    return 0


def network_connection_check():
    log("*** Checking connection to people.redhat.com ***")
    ret = bash("ping -c 10 people.redhat.com")
    log(ret)
    if ret.code == 0:
        log("*** Connection to server succesful ***")
        return 0
    else:
        log("People.redhat.com connection fail !!!!")  
        log("Cannot connect to people.redhat.com, please verify internet connection !!!")
        return 1
    return 0


def ovs_running_check():
    log("*** Checking for running instance of Openvswitch ***")
    if bash("pgrep ovs-vswitchd || pgrep ovsdb-server").value():
        log("It appears Openvswitch may be running, please stop all services and processes")
    else:
        log("ovs-vswitchd and ovsdb-server check OK")
    return 0


def download_VNF_image():
    with pushd(case_path):
        one_queue_image = get_env("one_queue_image")
        two_queue_image = get_env("two_queue_image")
        if os.path.exists(f"{case_path}/{one_queue_image}"):
            pass
        else:
            log_info = """
            ***********************************************************************
            Downloading and decompressing VNF image. This may take a while!
            ***********************************************************************
            """
            log(log_info)
            one_queue_zip = get_env("one_queue_zip")
            cmd = f"""
            wget http://netqe-bj.usersys.redhat.com/share/tli/vsperf_img/{one_queue_image} > /dev/null 2>&1
            #wget people.redhat.com/ctrautma/{one_queue_zip} > /dev/null 2>&1
            #lrzip -d {one_queue_zip}
            #rm -f {one_queue_zip}
            """
            log_and_run(cmd)
            pass

        if os.path.exists(f"{case_path}/{two_queue_image}"):
            pass
        else:
            log_info = """
            ***********************************************************************
            Downloading and decompressing VNF image. This may take a while!
            ***********************************************************************
            """
            log(log_info)
            two_queue_zip = get_env("two_queue_zip")
            cmd = f"""
            wget http://netqe-bj.usersys.redhat.com/share/tli/vsperf_img/{two_queue_image} > /dev/null 2>&1
            # wget people.redhat.com/ctrautma/{two_queue_zip} > /dev/null 2>&1
            # lrzip -d {two_queue_zip}
            # rm -f {two_queue_zip}
            """
            log_and_run(cmd)
            pass

        udev_file = "60-persistent-net.rules"
        data = """
        ACTION=="add", SUBSYSTEM=="net", KERNELS=="0000:03:00.0", NAME:="eth1"
        ACTION=="add", SUBSYSTEM=="net", KERNELS=="0000:04:00.0", NAME:="eth2"
        """
        log("add net rules to guest image")
        log(data)
        local.path(udev_file).write(data)


    cmd = f"""
    virt-copy-in -a {case_path}/{one_queue_image} {udev_file} /etc/udev/rules.d/
    virt-copy-in -a {case_path}/{two_queue_image} {udev_file} /etc/udev/rules.d/
    """
    log_and_run(cmd)

    dpdk_url = get_env("dpdk_url")
    dpdk_tool_url = get_env("dpdk_tool_url")
    dpdk_ver = get_env("dpdk_ver")

    cmd =  f"""
    rm -rf /root/{dpdk_ver}
    mkdir -p /root/{dpdk_ver}
    wget -P /root/{dpdk_ver}/ {dpdk_url} > /dev/null 2>&1
    wget -P /root/{dpdk_ver}/ {dpdk_tool_url} > /dev/null 2>&1
    virt-copy-in -a {case_path}/{one_queue_image} /root/{dpdk_ver} /root/
    virt-copy-in -a {case_path}/{two_queue_image} /root/{dpdk_ver} /root/
    sleep 5
    """
    log_and_run(cmd)
    
    return 0


def install_rpms():
    with pushd(case_path):
        all_package = """
        yum-utils
        scl-utils
        python36
        python36-devel
        python-netifaces
        python3-pyelftools
        wget
        nano
        ftp
        git
        tuna
        openssl
        sysstat
        libvirt
        libvirt-devel
        virt-install
        virt-manager
        virt-viewer
        czmq-devel
        libguestfs-tools
        ethtool
        vim
        lrzip
        libnl3-devel
        """.split()
        for pack in all_package:
            check_install(pack)
        bash("systemctl restart libvirtd")
    return 0

def ovs_bridge_with_kernel(nic1_name, nic2_name):
    cmd = f"""
	modprobe openvswitch
	systemctl stop openvswitch
	sleep 3
	systemctl start openvswitch
	sleep 3
	ovs-vsctl --if-exists del-br ovsbr0
	sleep 5

    ovs-vsctl set Open_vSwitch . other_config={{}}
	systemctl restart openvswitch

    ovs-vsctl --timeout 10 add-br ovsbr0
    ovs-vsctl --timeout 10 set Open_vSwitch . other_config:max-idle=30000

    ip addr flush dev {nic1_name}
    ip link set dev {nic1_name} up
    ovs-vsctl --timeout 10 add-port ovsbr0 {nic1_name}
    
    ip addr flush dev {nic2_name}
    ip link set dev {nic2_name} up
    ovs-vsctl --timeout 10 add-port ovsbr0 {nic2_name}
    
    ip tuntap del tap0 mode tap
    ip tuntap add tap0 mode tap
    ip addr flush dev tap0
    ip link set dev tap0 up
    ovs-vsctl --timeout 10 add-port ovsbr0 tap0
    
    ip tuntap del tap1 mode tap
    ip tuntap add tap1 mode tap
    ip addr flush dev tap1
    ip link set dev tap1 up
    ovs-vsctl --timeout 10 add-port ovsbr0 tap1

    ovs-vsctl set Interface {nic1_name}  ofport_request=1
    ovs-vsctl set Interface {nic2_name}  ofport_request=2
    ovs-vsctl set Interface tap0 ofport_request=3
    ovs-vsctl set Interface tap1 ofport_request=4

    ovs-ofctl -O OpenFlow13 --timeout 10 del-flows ovsbr0 
    ovs-ofctl -O OpenFlow13 --timeout 10 add-flow ovsbr0 in_port=1,idle_timeout=0,action=output:3
    ovs-ofctl -O OpenFlow13 --timeout 10 add-flow ovsbr0 in_port=3,idle_timeout=0,action=output:1
    ovs-ofctl -O OpenFlow13 --timeout 10 add-flow ovsbr0 in_port=4,idle_timeout=0,action=output:2
    ovs-ofctl -O OpenFlow13 --timeout 10 add-flow ovsbr0 in_port=2,idle_timeout=0,action=output:4

	sleep 2
	ovs-vsctl show
    """
    run(cmd)
    return 0


def ovs_bridge_with_dpdk(nic1_mac, nic2_mac, mtu_val, pmd_cpu_mask):
    cmd = f"""
	modprobe openvswitch
	systemctl stop openvswitch
	sleep 3
	systemctl start openvswitch
	sleep 3
	ovs-vsctl --if-exists del-br ovsbr0
	sleep 5

	ovs-vsctl set Open_vSwitch . other_config={{}}
	ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true
	ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-socket-mem="4096,4096"
	ovs-vsctl set Open_vSwitch . other_config:pmd-cpu-mask="{pmd_cpu_mask}"
    ovs-vsctl --no-wait set Open_vSwitch . other_config:vhost-iommu-support=true
	systemctl restart openvswitch
	sleep 3
	ovs-vsctl add-br ovsbr0 -- set bridge ovsbr0 datapath_type=netdev

    ovs-vsctl add-port ovsbr0 dpdk0 -- set Interface dpdk0 type=dpdk options:dpdk-devargs="class=eth,mac={nic1_mac}" mtu_request={mtu_val}
    ovs-vsctl add-port ovsbr0 dpdk1 -- set Interface dpdk1 type=dpdk options:dpdk-devargs="class=eth,mac={nic2_mac}" mtu_request={mtu_val}

    ovs-vsctl add-port ovsbr0 vhost0 -- set interface vhost0 type=dpdkvhostuserclient options:vhost-server-path=/tmp/vhost0 mtu_request={mtu_val}
    ovs-vsctl add-port ovsbr0 vhost1 -- set interface vhost1 type=dpdkvhostuserclient options:vhost-server-path=/tmp/vhost1 mtu_request={mtu_val}

    ovs-vsctl set Interface dpdk0  ofport_request=1
    ovs-vsctl set Interface dpdk1  ofport_request=2
    ovs-vsctl set Interface vhost0 ofport_request=3
    ovs-vsctl set Interface vhost1 ofport_request=4

    ovs-ofctl del-flows ovsbr0
    /usr/bin/ovs-ofctl -O OpenFlow13 --timeout 10 add-flow ovsbr0 idle_timeout=0,in_port=1,action=output:3
    /usr/bin/ovs-ofctl -O OpenFlow13 --timeout 10 add-flow ovsbr0 idle_timeout=0,in_port=3,action=output:1
    /usr/bin/ovs-ofctl -O OpenFlow13 --timeout 10 add-flow ovsbr0 idle_timeout=0,in_port=2,action=output:4
    /usr/bin/ovs-ofctl -O OpenFlow13 --timeout 10 add-flow ovsbr0 idle_timeout=0,in_port=4,action=output:2
	#ovs-ofctl add-flow ovsbr0 actions=NORMAL

	sleep 2
	ovs-vsctl show
    """
    run(cmd)
    return 0


def vcpupin_in_xml(numa_node, template_xml, new_xml, cpu_list):
    with pushd(case_path):
        config_file_checks()
        local.path(template_xml).copy(new_xml)
        xml_tool.xml_add_vcpupin_item(new_xml, len(cpu_list))
        xml_tool.update_numa(new_xml,numa_node)
        for i in range(len(cpu_list)):
            xml_tool.update_vcpu(new_xml, i, cpu_list[i])
    return 0


def start_guest(guest_xml):
    with pushd(case_path):
        run("systemctl list-units --state=stop --type=service | grep libvirtd || systemctl restart libvirtd")
        download_VNF_image()
        cmd = f"""
        virsh define {case_path}/{guest_xml}
        virsh start gg
        """
        run(cmd)
    return 0


def destroy_guest():
    cmd = """
    virsh destroy gg
    virsh undefine gg
    """
    run(cmd)
    return 0


def configure_guest():
    cmd = """
        stty rows 24 cols 120
        nmcli dev set eth1 managed no
        nmcli dev set eth2 managed no
        systemctl stop firewalld
        iptables -t filter -P INPUT ACCEPT
        iptables -t filter -P FORWARD ACCEPT
        iptables -t filter -P OUTPUT ACCEPT
        iptables -t mangle -P PREROUTING ACCEPT
        iptables -t mangle -P INPUT ACCEPT
        iptables -t mangle -P FORWARD ACCEPT
        iptables -t mangle -P OUTPUT ACCEPT
        iptables -t mangle -P POSTROUTING ACCEPT
        iptables -t nat -P PREROUTING ACCEPT
        iptables -t nat -P INPUT ACCEPT
        iptables -t nat -P OUTPUT ACCEPT
        iptables -t nat -P POSTROUTING ACCEPT
        iptables -t filter -F
        iptables -t filter -X
        iptables -t mangle -F
        iptables -t mangle -X
        iptables -t nat -F
        iptables -t nat -X
        ip6tables -t filter -P INPUT ACCEPT
        ip6tables -t filter -P FORWARD ACCEPT
        ip6tables -t filter -P OUTPUT ACCEPT
        ip6tables -t mangle -P PREROUTING ACCEPT
        ip6tables -t mangle -P INPUT ACCEPT
        ip6tables -t mangle -P FORWARD ACCEPT
        ip6tables -t mangle -P OUTPUT ACCEPT
        ip6tables -t mangle -P POSTROUTING ACCEPT
        ip6tables -t nat -P PREROUTING ACCEPT
        ip6tables -t nat -P INPUT ACCEPT
        ip6tables -t nat -P OUTPUT ACCEPT
        ip6tables -t nat -P POSTROUTING ACCEPT
        ip6tables -t filter -F
        ip6tables -t filter -X
        ip6tables -t mangle -F
        ip6tables -t mangle -X
        ip6tables -t nat -F
        ip6tables -t nat -X
        ip -d addr show
    """
    pts = bash("virsh ttyconsole gg").value()
    ret = my_tool.run_cmd_get_output(pts, cmd)
    log(ret)
    return 0

def check_guest_kernel_bridge_result():
    cmd = f"""
    ip -d link show br0
    ifconfig br0
    """
    pts = bash("virsh ttyconsole gg").value()
    ret = my_tool.run_cmd_get_output(pts, cmd)
    log(ret)
    pass

def guest_start_kernel_bridge():
    cmd = f"""
    brctl addbr br0
    ip addr add 192.168.1.2/24 dev eth1
    ip link set dev eth1 up
    brctl addif br0 eth1
    ip addr add 192.168.1.3/24 dev eth2
    ip link set dev eth2 up
    brctl addif br0 eth2
    ip addr add 1.1.1.5/16 dev br0
    ip link set dev br0 up
    # arp -s 1.1.1.10 3c:fd:fe:ad:bc:e8
    # arp -s 1.1.2.10 3c:fd:fe:ad:bc:e9
    sysctl -w net.ipv4.ip_forward=1
    yum install -y tuna
    tuned-adm profile network-latency
    sysctl -w net.ipv4.conf.all.rp_filter=0
    sysctl -w net.ipv4.conf.eth0.rp_filter=0
    """
    pts = bash("virsh ttyconsole gg").value()
    ret = my_tool.run_cmd_get_output(pts, cmd)
    log(ret)
    pass

def check_guest_testpmd_result():
    cmd = f"""
    show port info all
    show port stats all
    """
    pts = bash("virsh ttyconsole gg").value()
    ret = my_tool.run_cmd_get_output(pts, cmd,"testpmd>")
    log(ret)
    return 0

# {modprobe  vfio enable_unsafe_noiommu_mode=1}
def guest_start_testpmd(queue_num, guest_cpu_list, rxd_size, txd_size,max_pkt_len,fwd_mode):
    dpdk_ver = get_env("dpdk_ver")
    cmd = f"""
    /root/one_gig_hugepages.sh 1
    rpm -ivh /root/dpdkrpms/{dpdk_ver}/dpdk*.rpm
    rpm -ivh /root//{dpdk_ver}/dpdk*.rpm
    echo "options vfio enable_unsafe_noiommu_mode=1" > /etc/modprobe.d/vfio.conf
    modprobe -r vfio_iommu_type1
    modprobe -r vfio-pci
    modprobe -r vfio
    modprobe  vfio
    modprobe vfio-pci
    ip link set eth1 down
    ip link set eth2 down
    ip link show
    dpdk-devbind -b vfio-pci 0000:03:00.0
    dpdk-devbind -b vfio-pci 0000:04:00.0
    dpdk-devbind --status
    """
    pts = bash("virsh ttyconsole gg").value()
    ret = my_tool.run_cmd_get_output(pts, cmd)
    log(ret)
    # from remote_pdb import set_trace
    # set_trace() 

    num_core = 2
    if queue_num == 1:
        num_core = 2
    else:
        num_core = 4

    hw_vlan_flag = ""
    legacy_mem = ""

    dpdk_version = int(get_env("dpdk_ver").split('-')[0])
    if dpdk_version >= 1811:
        legacy_mem = " --legacy-mem "
        hw_vlan_flag = ""
    else:
        legacy_mem = ""
        hw_vlan_flag = "--disable-hw-vlan"
    
    extra_parameter = ""
    if fwd_mode == "mac":
        port0_peer_mac = get_env("TRAFFICGEN_TREX_PORT1")
        port1_peer_mac = get_env("TRAFFICGEN_TREX_PORT2")
        extra_parameter = f"--eth-peer=0,{port0_peer_mac} --eth-peer=1,{port1_peer_mac}"

    cmd_test = f"""testpmd -l {guest_cpu_list}  \
    --socket-mem 1024 \
    {legacy_mem} \
    -n 4 \
    -- \
    --forward-mode={fwd_mode} \
    --port-topology=paired \
    {hw_vlan_flag} \
    --disable-rss \
    -i \
    --rxq={queue_num} \
    --txq={queue_num} \
    --rxd={rxd_size} \
    --txd={txd_size} \
    --nb-cores={num_core} \
    --max-pkt-len={max_pkt_len} \
    {extra_parameter} \
    --auto-start
    """
    ret = my_tool.run_cmd_get_output(pts,cmd_test,"testpmd>")
    log(ret)
    return 0

@set_check(0)
def clear_dpdk_interface():
    if bash("rpm -qa | grep dpdk-tools").value():
        bus_list = bash(r"dpdk-devbind -s | grep  -E drv=vfio-pci\|drv=igb | awk '{print $1}'").value()
        print(bus_list)
        for i in str(bus_list).split(os.linesep):
            print("*************************************************************")
            print(i)
            print("*********************************************************")
            if len(i.strip()) > 0:
                kernel_driver = bash(f"lspci -s {i} -v | grep Kernel  | grep modules  | awk '{{print $NF}}'").value()
                log_and_run(f"dpdk-devbind -b {kernel_driver} {i}")
    return 0

def clear_env():
    cmd = """
    systemctl start openvswitch
    ovs-vsctl --if-exists del-br ovsbr0
    virsh destroy gg
    virsh undefine gg
    systemctl stop openvswitch
    ip tuntap del tap0 mode tap
    ip tuntap del tap1 mode tap
    """
    log_and_run(cmd,"0,1")
    clear_dpdk_interface()
    clear_hugepage()
    log_and_run("ip link show")
    log_and_run("sleep 10")
    log_and_run("ip link show")
    return 0

def bonding_test_trex(t_time,pkt_size,dst_mac_one,dst_mac_two):
    trex_server_ip = get_env("TRAFFICGEN_TREX_HOST_IP_ADDR")
    with pushd(case_path):
        ret = bash(f"ping {trex_server_ip} -c 3")
        if ret.code != 0:
            log("Trex server {} not up please check ".format(trex_server_ip))
        
        trex_url = "http://netqe-bj.usersys.redhat.com/share/wanghekai/v2.59.tar.gz"
        trex_dir = os.path.basename(trex_url).replace(".tar.gz","")
        trex_name = os.path.basename(trex_url)
        if not os.path.exists(trex_dir):
            cmd = f"""
            wget {trex_url} > /dev/null 2>&1
            tar -xvf {trex_name} > /dev/null 2>&1
            """
            log_and_run(cmd)
        import time
        time.sleep(3)
        # trex_port_1 = get_env("TRAFFICGEN_TREX_PORT1")
        # trex_port_2 = get_env("TRAFFICGEN_TREX_PORT2")
        # log_and_run(f""" python ./trex_sport.py -c {trex_server_ip} -d '{trex_port_1} {trex_port_2}' -t {t_time} --pkt_size={pkt_size} -m 10 """)
        log_and_run(f""" python ./trex_sport.py -c {trex_server_ip} -d '{dst_mac_one} {dst_mac_two}' -t {t_time} --pkt_size={pkt_size} -m 10 """)
    return 0

def attch_sriov_vf_to_vm(xml_file,vm,vlan_id=0):
    vf1_bus_info = my_tool.get_bus_from_name(get_env("NIC1_VF"))
    vf2_bus_info = my_tool.get_bus_from_name(get_env("NIC2_VF"))
    
    vf1_bus_info = vf1_bus_info.replace(":",'_')
    vf1_bus_info = vf1_bus_info.replace(".",'_')
    
    vf2_bus_info = vf2_bus_info.replace(":",'_')
    vf2_bus_info = vf2_bus_info.replace(".",'_')

    log(vf1_bus_info)
    log(vf2_bus_info)
    
    vf1_domain = vf1_bus_info.split('_')[0]
    vf1_bus    = vf1_bus_info.split('_')[1]
    vf1_slot   = vf1_bus_info.split('_')[2]
    vf1_func   = vf1_bus_info.split('_')[3]

    vf2_domain = vf2_bus_info.split('_')[0]
    vf2_bus    = vf2_bus_info.split('_')[1]
    vf2_slot   = vf2_bus_info.split('_')[2]
    vf2_func   = vf2_bus_info.split('_')[3]

    vlan_item = """
    <interface type='hostdev' managed='yes'>
        <mac address='{}'/>
        <vlan >
            <tag id='{}'/>
        </vlan>
        <driver name='vfio'/>
        <source >
            <address type='pci' domain='0x{}' bus='0x{}' slot='0x{}' function='0x{}'/>
        </source >
        <address type='pci' domain='{}' bus='{}' slot='{}' function='{}'/>
    </interface >
    """

    item = """
    <interface type='hostdev' managed='yes'>
        <mac address='{}'/>
        <driver name='vfio'/>
        <source >
            <address type='pci' domain='0x{}' bus='0x{}' slot='0x{}' function='0x{}'/>
        </source >
        <address type='pci' domain='{}' bus='{}' slot='{}' function='{}'/>
    </interface >
    """

    vf1_xml_path = os.getcwd() + "/vf1.xml"
    vf2_xml_path = os.getcwd() + "/vf2.xml"
    if os.path.exists(vf1_xml_path):
        os.remove(vf1_xml_path)
    if os.path.exists(vf2_xml_path):
        os.remove(vf2_xml_path)
    local.path(vf1_xml_path).touch()
    local.path(vf2_xml_path).touch()
    vf1_f_obj = local.path(vf1_xml_path)
    vf2_f_obj = local.path(vf2_xml_path)
     
    
    import xml.etree.ElementTree as xml

    if vlan_id != 0:
        vf1_format_list = ['52:54:00:11:8f:ea', vlan_id ,vf1_domain ,vf1_bus, vf1_slot, vf1_func, '0x0000', '0x03', '0x0', '0x0'] 
        vf1_vlan_item = vlan_item.format(*vf1_format_list)
        vf1_vlan_obj = xml.fromstring(vf1_vlan_item)
        vf1_f_obj.write(xml.tostring(vf1_vlan_obj))

        vf2_format_list = ['52:54:00:11:8f:eb', vlan_id, vf2_domain, vf2_bus, vf2_slot, vf2_func, '0x0000', '0x04', '0x0', '0x0']
        vf2_vlan_item = vlan_item.format(*vf2_format_list)
        vf2_vlan_obj = xml.fromstring(vf2_vlan_item)
        vf2_f_obj.write(xml.tostring(vf2_vlan_obj))
    else:
        vf1_format_list = ['52:54:00:11:8f:ea' ,vf1_domain, vf1_bus, vf1_slot, vf1_func, '0x0000', '0x03', '0x0', '0x0'] 
        vf1_novlan_item = item.format(*vf1_format_list)
        vf1_novlan_obj = xml.fromstring(vf1_novlan_item)
        vf1_f_obj.write(xml.tostring(vf1_novlan_obj))

        vf2_format_list = ['52:54:00:11:8f:eb' ,vf2_domain ,vf2_bus, vf2_slot ,vf2_func, '0x0000', '0x04', '0x0', '0x0']
        vf2_novlan_item = item.format(*vf2_format_list)
        vf2_novlan_obj = xml.fromstring(vf2_novlan_item)
        vf2_f_obj.write(xml.tostring(vf2_novlan_obj))
    
    cmd = f"""
    sleep 10
    echo "#################################################"
    cat {vf1_xml_path}
    echo "#################################################"
    cat {vf2_xml_path}
    echo "#################################################"
    virsh attach-device {vm} {vf1_xml_path}
    sleep 5
    virsh dumpxml {vm}
    sleep 10
    virsh attach-device {vm} {vf2_xml_path}
    sleep 5
    virsh dumpxml {vm}
    """
    log_and_run(cmd)

    return 0

def update_xml_sriov_vf_port(xml_file,vlan_id=0):
    vf1_bus_info = my_tool.get_bus_from_name(get_env("NIC1_VF"))
    vf2_bus_info = my_tool.get_bus_from_name(get_env("NIC2_VF"))
    
    vf1_bus_info = vf1_bus_info.replace(":",'_')
    vf1_bus_info = vf1_bus_info.replace(".",'_')
    
    vf2_bus_info = vf2_bus_info.replace(":",'_')
    vf2_bus_info = vf2_bus_info.replace(".",'_')

    log(vf1_bus_info)
    log(vf2_bus_info)
    
    vf1_domain = vf1_bus_info.split('_')[0]
    vf1_bus    = vf1_bus_info.split('_')[1]
    vf1_slot   = vf1_bus_info.split('_')[2]
    vf1_func   = vf1_bus_info.split('_')[3]

    vf2_domain = vf2_bus_info.split('_')[0]
    vf2_bus    = vf2_bus_info.split('_')[1]
    vf2_slot   = vf2_bus_info.split('_')[2]
    vf2_func   = vf2_bus_info.split('_')[3]

    vlan_item = """
    <interface type='hostdev' managed='yes'>
        <mac address='{}'/>
        <vlan >
            <tag id='{}'/>
        </vlan>
        <driver name='vfio'/>
        <source >
            <address type='pci' domain='0x{}' bus='0x{}' slot='0x{}' function='0x{}'/>
        </source >
        <address type='pci' domain='{}' bus='{}' slot='{}' function='{}'/>
    </interface >
    """

    item = """
    <interface type='hostdev' managed='yes'>
        <mac address='{}'/>
        <driver name='vfio'/>
        <source >
            <address type='pci' domain='0x{}' bus='0x{}' slot='0x{}' function='0x{}'/>
        </source >
        <address type='pci' domain='{}' bus='{}' slot='{}' function='{}'/>
    </interface >
    """

    xml_tool.remove_item_from_xml(xml_file,"./devices/interface[@type='hostdev']")

    if vlan_id != 0:
        vf1_format_list = ['52:54:00:11:8f:ea', vlan_id ,vf1_domain ,vf1_bus, vf1_slot, vf1_func, '0x0000', '0x03', '0x0', '0x0'] 
        vf1_vlan_item = vlan_item.format(*vf1_format_list)
        xml_tool.add_item_from_xml(xml_file,"./devices",vf1_vlan_item)

        vf2_format_list = ['52:54:00:11:8f:eb', vlan_id, vf2_domain, vf2_bus, vf2_slot, vf2_func, '0x0000', '0x04', '0x0', '0x0']
        vf2_vlan_item = vlan_item.format(*vf2_format_list)
        xml_tool.add_item_from_xml(xml_file,"./devices" ,vf2_vlan_item)
    else:
        vf1_format_list = ['52:54:00:11:8f:ea' ,vf1_domain, vf1_bus, vf1_slot, vf1_func, '0x0000', '0x03', '0x0', '0x0'] 
        vf1_novlan_item = item.format(*vf1_format_list)
        xml_tool.add_item_from_xml(xml_file,"./devices",vf1_novlan_item)

        vf2_format_list = ['52:54:00:11:8f:eb' ,vf2_domain ,vf2_bus, vf2_slot ,vf2_func, '0x0000', '0x04', '0x0', '0x0']
        vf2_novlan_item = item.format(*vf2_format_list)
        xml_tool.add_item_from_xml(xml_file,"./devices", vf2_novlan_item)
    return 0


def update_xml_vnet_port(xml_file):
    append_item = """
        <interface type="bridge">
            <mac address="52:54:00:bb:63:7b" />
            <source bridge="virbr0" />
            <model type="virtio" />
            <address bus="0x02" domain="0x0000" function="0x0" slot="0x00" type="pci" />
        </interface>
    """

    item = """
        <interface type='bridge'>
            <mac address='{}'/>
            <source bridge='{}'/>
            <virtualport type='openvswitch'/>
            <address type='pci' domain='{}' bus='{}' slot='{}' function='{}'/>
            <target dev='{}'/>
            <model type='virtio'/>
        </interface>
    """
    xml_tool.remove_item_from_xml(xml_file,"./devices/interface[@type='bridge']")
    xml_tool.add_item_from_xml(xml_file,"./devices", append_item)

    
    vnet_format_list_one = ['52:54:00:11:8f:ea','ovsbr0','0x0000','0x03','0x0','0x0','tap0']
    vnet_format_item_one = item.format(*vnet_format_list_one)
    xml_tool.add_item_from_xml(xml_file,"./devices" ,vnet_format_item_one)

    vnet_format_list_two = ['52:54:00:11:8f:eb','ovsbr0','0x0000','0x04','0x0','0x0','tap1']
    vnet_format_item_two = item.format(*vnet_format_list_two)
    xml_tool.add_item_from_xml(xml_file,"./devices",vnet_format_item_two)
    return 0


def update_xml_vhostuser(xml_file,q_num):
    xml_tool.remove_item_from_xml(xml_file,"./devices/interface[@type='vhostuser']")
    item = """
        <interface type='vhostuser'>
            <mac address='{}'/>
            <source type='unix' path='{}' mode='server'/>
            <model type='virtio'/>
            <driver name='vhost' iommu='on' ats='on' queues="{}"/>
            <address type='pci' domain='{}' bus='{}' slot='{}' function='{}'/>
        </interface>
    """
    f_list_one = ['52:54:00:11:8f:ea','/tmp/vhost0',q_num,'0x0000','0x03','0x0','0x0']
    f_item_one = item.format(*f_list_one)
    xml_tool.add_item_from_xml(xml_file,"./devices",f_item_one)

    f_list_two = ['52:54:00:11:8f:eb','/tmp/vhost1',q_num,'0x0000','0x04','0x0','0x0']
    f_item_two = item.format(*f_list_two)
    xml_tool.add_item_from_xml(xml_file,"./devices",f_item_two)
    return 0

def ovs_dpdk_pvp_test(q_num,mtu_val,pkt_size,cont_time):
    clear_env()
    nic1_name = get_env("NIC1")
    nic2_name = get_env("NIC2")
    nic1_mac = my_tool.get_mac_from_name(nic1_name)
    nic2_mac = my_tool.get_mac_from_name(nic2_name)
    numa_node = bash(f"cat /sys/class/net/{nic1_name}/device/numa_node").value()

    log("enable dpdk now")
    enable_dpdk(nic1_mac,nic2_mac)

    log("config openvswitch with dpdk ")
    pmd_cpu_2_list = [get_env("PMD_CPU_1"),get_env("PMD_CPU_2")]
    pmd_cpu_4_list = [get_env("PMD_CPU_1"),get_env("PMD_CPU_2"),get_env("PMD_CPU_3"),get_env("PMD_CPU_4")]
    if q_num == 1:
        cpu_mask = my_tool.get_pmd_masks(" ".join(pmd_cpu_2_list))
        vcpu_list = [get_env("VCPU1"),get_env("VCPU2"),get_env("VCPU3")]
        ovs_bridge_with_dpdk(nic1_mac,nic2_mac,mtu_val,cpu_mask)
    else:
        cpu_mask = my_tool.get_pmd_masks(" ".join(pmd_cpu_4_list))
        vcpu_list = [get_env("VCPU1"),get_env("VCPU2"),get_env("VCPU3"),get_env("VCPU4"),get_env("VCPU5")]
        ovs_bridge_with_dpdk(nic1_mac,nic2_mac,mtu_val,cpu_mask)
    
    log("update guest xml config file")
    new_xml = "g1.xml"
    vcpupin_in_xml(numa_node,"guest.xml",new_xml,vcpu_list)
    update_xml_vhostuser(new_xml,q_num)

    if q_num == 1:
        xml_tool.update_image_source(new_xml,case_path + "/" + get_env("one_queue_image"))
    else:
        xml_tool.update_image_source(new_xml,case_path + "/" + get_env("two_queue_image"))
    
    log("start and config guest Now")
    start_guest(new_xml)
    configure_guest()

    log("guest start testpmd test Now")
    if q_num == 1:
        guest_cpu_list="0,1,2"
    else:
        guest_cpu_list="0,1,2,3,4"
    guest_start_testpmd(q_num,guest_cpu_list,get_env("RXD_SIZE"),get_env("TXD_SIZE"),mtu_val,"io")

    log("ovs dpdk PVP performance test Begin Now")
    trex_port_1 = get_env("TRAFFICGEN_TREX_PORT1")
    trex_port_2 = get_env("TRAFFICGEN_TREX_PORT2")
    bonding_test_trex(cont_time,pkt_size,trex_port_1,trex_port_2)

    check_guest_testpmd_result()

    return 0

def ovs_kernel_datapath_test(q_num,pkt_size,cont_time):
    clear_env()
    nic1_name = get_env("NIC1")
    nic2_name = get_env("NIC2")
    numa_node = bash(f"cat /sys/class/net/{nic1_name}/device/numa_node").value()

    if q_num == 1:
        vcpu_list = [ get_env("VCPU1"),get_env("VCPU2"),get_env("VCPU3")]
        ovs_bridge_with_kernel(nic1_name,nic2_name)
    else:
        vcpu_list = [ get_env("VCPU1"),get_env("VCPU2"),get_env("VCPU3"),get_env("VCPU4"),get_env("VCPU5")]
        ovs_bridge_with_kernel(nic1_name,nic2_name)
        pass
    new_xml = "g1.xml"
    vcpupin_in_xml(numa_node,"guest.xml",new_xml,vcpu_list) 
    update_xml_vnet_port(new_xml)

    if q_num == 1:
        xml_tool.update_image_source(new_xml,case_path + "/" + get_env("one_queue_image"))
    else:
        xml_tool.update_image_source(new_xml,case_path + "/" + get_env("two_queue_image"))

    start_guest(new_xml)

    configure_guest()

    guest_start_kernel_bridge()

    log("ovs kernel datapath PVP performance test Begin Now")
    trex_port_1 = get_env("TRAFFICGEN_TREX_PORT1")
    trex_port_2 = get_env("TRAFFICGEN_TREX_PORT2")
    bonding_test_trex(cont_time,pkt_size,trex_port_1,trex_port_2)

    check_guest_kernel_bridge_result()

    return 0

def sriov_pci_passthrough_test(q_num,pkt_size,cont_time):
    clear_env()
    numa_node = bash("cat /sys/class/net/{}/device/numa_node".format(get_env("NIC1_VF"))).value()
    vcpu_list = [ get_env("VCPU1"),get_env("VCPU2"),get_env("VCPU3")]
    if q_num != 1:
        vcpu_list = [ get_env("VCPU1"),get_env("VCPU2"),get_env("VCPU3"),get_env("VCPU4"),get_env("VCPU5")]
    new_xml = "g1.xml"
    vcpupin_in_xml(numa_node,"guest.xml",new_xml,vcpu_list)
    #clear the old hostdev config and update xml file
    xml_tool.remove_item_from_xml(new_xml,"./devices/interface[@type='hostdev']")
    # Here because of the limit of p35 archtechture , I can not add two vf into vm at the same time 
    # So , make a workaround , add vf with virsh attach-device two times

    #start vm
    if q_num == 1:
        xml_tool.update_image_source(new_xml,case_path + "/" + get_env("one_queue_image"))
    else:
        xml_tool.update_image_source(new_xml,case_path + "/" + get_env("two_queue_image"))
    
    start_guest(new_xml)

    #Here attach vf to vm 
    attch_sriov_vf_to_vm(new_xml,"gg")

    configure_guest

    log("guest start testpmd test Now")
    if q_num == 1:
        guest_cpu_list="0,1,2"
    else:
        guest_cpu_list="0,1,2,3,4"

    guest_start_testpmd(q_num,guest_cpu_list,get_env("SRIOV_RXD_SIZE"),get_env("SRIOV_TXD_SIZE"),pkt_size,"mac")

    log("sriov pci passthrough PVP performance test Begin Now")
    bonding_test_trex(cont_time,pkt_size,"52:54:00:11:8f:ea","52:54:00:11:8f:eb")

    check_guest_testpmd_result()

    return 0


def run_tests(test_list):
    print(os.environ)
    if test_list == "pvp_cont":
        with enter_phase("PVP-1500-BYTES-CONT-1Q-2PMD-TEST"):
            data = """
            *************************************************************
            Running 1500 Byte PVP verify check
            For 1Q 2PMD Test
            *************************************************************
            """
            log(data)
            ovs_dpdk_pvp_test(1,1500,1500,30)
            pass
    
    if test_list == "ALL" or test_list == "SRIOV":
        with enter_phase("SRIOV 64/1500 Bytes SR-IOV TEST"):
            data = """
            ************************************************
            Running 64/1500 Bytes SR-IOV VSPerf TEST
            ************************************************
            """
            log(data)
            sriov_pci_passthrough_test(1,64,30)
            sriov_pci_passthrough_test(2,1500,30)
            pass

    if test_list == "ALL" or test_list == "1Q":
        with enter_phase("Running 64/1500 Byte PVP verify check FOR 1Q AND 2PMD TEST"):
            data = """
            *************************************************************
            Running 1500 Byte PVP verify check
            For 1Q 2PMD Test
            *************************************************************
            """
            log(data)
            ovs_dpdk_pvp_test(1,64,64,30)
            log("***************************************************************************************")
            # import time
            # time.sleep(10000)
            ovs_dpdk_pvp_test(1,1500,1500,30)
            pass


    if test_list == "ALL" or test_list == "2Q":
        with enter_phase("Running 64/1500 Byte PVP verify check FOR 2Q AND 4PMD TEST"):
            data = """
            *************************************************************
            Running 1500 Byte PVP verify check
            For 2Q 4PMD Test
            *************************************************************
            """
            log(data)
            ovs_dpdk_pvp_test(2,64,64,30)
            ovs_dpdk_pvp_test(2,1500,1500,30)
            pass

    if test_list == "ALL" or test_list == "Jumbo":
        with enter_phase("Running 2000/9000 Bytes 2PMD PVP OVS/DPDK VSPerf TEST"):
            data = """
            *************************************************************
            Running 2000/9000 Bytes 2PMD PVP OVS/DPDK VSPerf TEST
            *************************************************************
            """
            log(data)
            ovs_dpdk_pvp_test(1,2000,2000,30)
            ovs_dpdk_pvp_test(2,9000,9000,30)
            pass


    if test_list == "ALL" or test_list == "Kernel":
        with enter_phase("Running 64/1500 Bytes PVP OVS Kernel VSPerf TEST"):
            data = """
            ************************************************************
            Running 64/1500 Bytes PVP OVS Kernel VSPerf TEST
            ************************************************************
            """
            log(data)
            ovs_kernel_datapath_test(1,64,30)
            ovs_kernel_datapath_test(2,1500,30)
            pass
    

    return 0


def copy_config_files_to_log_folder():
    log_folder = get_env("NIC_LOG_FOLDER")
    bash("cp /root/RHEL_NIC_QUALIFICATION/Perf-Verify.conf {}".format(log_folder))
    return 0

def usage():
    data = """
    Usage: $progname[-t test to execute][-h print help]
    -t tests to execute['1Q, 2Q, Jumbo, Kernel, pvp_cont', 'SRIOV'] default is to run all tests
    -h print this help message
    """
    print(data)
    pass

def exit_with_error(str):
    print(f"Exit with {str}")
    log(f"""Exit with {str}""")
    send_command("sriov-github-vsperf")
    pass

def main(test_list="ALL"):
    # run all checks
    with enter_phase("OS DISTRO CHECK"):
        ret = os_check()
        if ret != 0:
            exit_with_error("OS CHECK FAILED")
        pass
    
    with enter_phase("HUGEPAGE CHECK"):
        ret = hugepage_checks()
        if ret != 0:
            exit_with_error("HUGEPAGE INVALID")
        pass

    with enter_phase("CONFIG CHECK"):
        ret = conf_checks()
        if ret != 0:
            exit_with_error("/proc/cmdline check FAILED")
        pass

    with enter_phase("CONFIG FILE CHECK"):
        ret = config_file_checks()
        if ret != 0:
            exit_with_error("CONFIG FAILE INVALIDE")
        pass

    with enter_phase("NIC CARD CHECK"):
        ret = nic_card_check()
        if ret != 0:
            exit_with_error("NIC CARDS CONFIG INVALID")
        pass

    with enter_phase("RPM PACKAGES CHECK"):
        ret = rpm_check()
        if ret != 0:
            exit_with_error("RPM CHECK FAILED")
        pass

    with enter_phase("NETWORK CONNECTION CHECK"):
        ret = network_connection_check()
        if ret != 0:
            exit_with_error("NETWORK CONNECTION CHECK FAILED")
        pass

    with enter_phase("OVS RUNNING CHECK"):
        ret = ovs_running_check()
        if ret != 0:
            exit_with_error("Openvswitch running check FAILED ")
        pass

    #finished running checks
    with enter_phase("VSPERF RUN TEST LIST"):
        ret = run_tests(test_list)
        if ret != 0:
            exit_with_error("VSPERF REPLACEMENT RUN TESTS FAILED")
        pass

    with enter_phase("COPY CONFIG FILES TO LOG FOLDER"):
        ret = copy_config_files_to_log_folder()
        if ret != 0:
            exit_with_error("COPY CONFIG FILE TO LOG FOLDER FAILED")
        pass

if __name__ == "__main__":
    send_command("rlJournalStart")
    main()
    send_command("rlJournalPrintText")
    send_command("rlJournalEnd")
    send_command("sriov-github-vsperf")
    pass
