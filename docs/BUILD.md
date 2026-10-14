# 编译教程

从零开始，把你自己那份原版 `drastic` 编译成带中文菜单的版本。

全程分四步：**准备环境 → 校验原版 → 构建 → 部署**。

---

## 0. 先确认目标匹配

这个补丁是对着**某个具体版本的 AArch64 PIE 可执行文件**写的，地址全部硬编码。
换一个版本，几乎所有常量都会对不上。

参考目标就是 **Anbernic RG DS（安伯尼克双屏掌机）** 所运行的 **ROCKNIX** 自带的那一份
`drastic`：原版提取自 **ROCKNIX RK3566 20261001** 的系统镜像
（`ROCKNIX-RK3566.aarch64-20261001-Specific.img.gz`），未经修改；本工具链产出的
补丁版已在 **RG DS 真机**上验证通过（中文菜单、游戏启动、金手指列表）。

| | 值 |
|---|---|
| 文件名 | `drastic` |
| 大小 | 1 411 544 字节 |
| md5 | `3e5a8b427561b9473751869de22cb40b` |
| 架构 | ELF64 AArch64, `ET_DYN`(PIE), stripped |
| 版本串 | 程序内含 `r2.5.2.2` |
| 来源设备 | Anbernic RG DS — ROCKNIX RK3566（Linux, AArch64） |
| 来源镜像 | `ROCKNIX-RK3566.aarch64-20261001-Specific.img.gz`（ROCKNIX 构建 20261001） |
| 实机验证 | 打补丁的产物已在 Anbernic RG DS 上运行通过 |

```sh
md5sum /path/to/drastic
# 3e5a8b427561b9473751869de22cb40b  /path/to/drastic    <- 必须一致
```

md5 不一致也**不一定**跑不起来，但 `patch.py` 里的十几条 `assert` 会拦住你 —— 那正是
它存在的意义：宁可构建失败，也不要产出会在设备上崩溃的二进制。

---

## 1. 环境准备

### 1.1 一台主机（Windows / Linux / macOS 都行）

工具全是 Python，唯一的本地编译依赖是 **zig**（用它的 `clang`/`lld` 交叉编译到
AArch64，免去装一整套 GNU 交叉工具链）。

```sh
python3 -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate

pip install ziglang capstone    # 必需
```

版本要求：

| 包 | 用途 | 参考版本 |
|---|---|---|
| Python | 全部主机端工具 | 3.8+（在 3.13 上验证） |
| `ziglang` | 交叉编译 payload | 0.16.0（在 0.16.0 上验证） |
| `capstone` | 构建时由 `patch.py` 用来查 ARM64 寄存器编号；重生成 `menu_sites.py` 也用它 | 5.0.9 |
| `unicorn` | harness 模拟器（可选） | 2.1.4 |
| `pillow` | harness 渲染 PNG（可选） | 12.x |

重新生成字体**不需要**额外依赖 —— 字形直接取自 `assets/unifont.hex`（见第 7 节）。

`build.sh` 会依次尝试：环境变量 `ZIG` → `PATH` 里的 `zig` → Python 包 `ziglang`
自带的 `zig`。都找不到就报错退出。

### 1.2 检查工具是否就位

```sh
zig version        # 0.16.0
python3 -c "import capstone; print(capstone.__version__)"
```

---

## 2. 校验原版

```sh
export DRASTIC_SRC=/path/to/your/drastic
python3 - <<'EOF'
import hashlib, os
p = os.environ["DRASTIC_SRC"]
d = open(p, "rb").read()
print(len(d), hashlib.md5(d).hexdigest())
EOF
```

期望输出 `1411544 3e5a8b427561b9473751869de22cb40b`。

> `DRASTIC_SRC` 不设的话默认找仓库根目录下的 `./drastic`。
> **永远不要把原版或打补丁后的可执行文件提交到 git**，`.gitignore` 已经拦了。

---

## 3. 构建

```sh
./build.sh
```

等价于下面两步，想看细节可以拆开跑。

### 3.1 第一步：交叉编译注入层

```sh
zig cc -target aarch64-linux-musl -ffreestanding -nostdlib -fno-builtin \
       -fno-stack-protector -fno-asynchronous-unwind-tables \
       -fomit-frame-pointer -O2 -c src/cjk.c -o build/cjk.o
zig cc <同样的标志> -c src/entry.S -o build/entry.o
zig cc <同样的标志> -c src/syms.S  -o build/syms.o
zig ld.lld -T src/link.ld --no-eh-frame-hdr -o build/payload.elf \
       build/entry.o build/syms.o build/cjk.o
```

要点：

- `-ffreestanding -nostdlib`：注入层**不能用 libc**，全部自带实现（含 `mmap`
  系统调用和 `malloc` 的替代）
- 链接脚本把 payload 钉死在 `0x150000`，这个地址必须落在原版两个 `PT_LOAD`
  之间的空洞里，见 `docs/INTERNALS.md`
- **字库不参与链接**：8 KB 的代码槽装不下 900 KB 的位图，字库是运行时从文件尾部
  `mmap` 进来的

产物 `build/payload.elf` 应该长这样：

```
payload syms: cjk_entry=0x150000 cjk_rect_entry=0x150054
payload image: filesz=memsz=0x2613 (9747 B), entry +0x0
```

### 3.2 第二步：打补丁

```sh
python3 tools/patch.py build/drastic.cjk
```

`patch.py` 做的事，按顺序：

1. 解析 `payload.elf`，取出 `.text/.rodata` 拼成一段连续镜像，要求
   **没有任何可写数据**（镜像被映射成 R-X）
2. 扫描镜像里所有 8 字节对齐的值，确保没有残留绝对地址 —— payload 是 PIE 的一个
   `PT_LOAD`，没有任何东西会给它做重定位，存了绝对指针在设备上就是悬空地址
3. 读 `assets/menu.bin`（1555 字节翻译表）接到镜像后面的 `0x152000`
4. 把原版里**每个引用被翻译字符串的 `adrp`+`add` 代码对**改写成一条 PC 相对的
   `adr`（80 处），把 **RELA 重定位项的 addend** 改成新地址（78 处）
5. 把之前那个 `PT_NOTE` 程序头改写成 `PT_LOAD`：`off=0x160000, vaddr=0x150000,
   flags=R-X(5), filesz=memsz`
6. 在文件 `0x170000` 处追加 895 838 字节字库 blob（**故意不挂任何程序头**）
7. 把 `draw_text()`（`0x87f00`）和 `fill_rect()`（`0x88430`）的第一条指令改成
   `b` 到注入层
8. 复查：`elf_bss`/`elf_brk` 必须和原版**逐位相同**，且不能出现可写又可执行的段

成功输出：

```
payload syms: cjk_entry=0x150000 cjk_rect_entry=0x150054
payload image: filesz=memsz=0x2613 (9747 B), entry +0x0
menu strtab: 0x152000, 1555 bytes, 135 strings (payload 0x346)
  code+rodata slot used: 838 / 8192 B
vendor : elf_bss=0x1681a0 elf_brk=0x3f32240  (.bss 0x169000..0x3f32240)
font blob at file 0x170000, 895838 bytes (cjk15|cjk10|cjk8|cjk16|uni_tab)
hook cjk_entry()    0x87f00: b 0x150000 (payload cjk_entry)
hook cjk_rect_entry() 0x88430: b 0x150054 (payload cjk_rect_entry)
menu: 80 code sites -> adr, 78 reloc addends rewritten
patched: elf_bss=0x1681a0 elf_brk=0x3f32240
written build/drastic.cjk (2403166 bytes, +991622)
```

### 3.3 第三步：自检

```sh
python3 tools/verify.py build/drastic.cjk
```

应当以 `result: ALL CHECKS PASSED` 结束。它会核对 ELF 不变量、两个钩子指令的
编码、以及字库 blob 的五个分节和 Unicode 映射表的单调性。如果产物与参考构建
完全一致，还会额外打印 `== the reference build, byte for byte`。

---

## 4. 部署到设备

**参考目标平台就是 RockNIX / Anbernic RG DS** —— 下面的产物 md5 即在该型掌机真机上
验证通过（原版与补丁版都出自/运行在这套系统上）。

> ⚠️ **关键一步：`drastic.cjk` 必须重命名成 `drastic`。**
> 系统的启动项找的是 `drastic` 这个文件名；`.cjk` 只是本项目用来区分"补丁版"的标记。
> 文件名不改，等于没替换 —— 要么仍启动原版，要么因找不到可执行文件而启动失败。

```sh
# 1) 主机 -> 设备。传过去叫什么无所谓，建议先保留 .cjk 后缀，避免当场覆盖掉原版
scp build/drastic.cjk root@<device>:/storage/.config/drastic/

# 2) 设备上：备份原版 → 重命名顶替 → 赋执行位
ssh root@<device>
cd /storage/.config/drastic
cp drastic drastic.orig.bak     # 留一份原版，出问题一键还原
mv drastic.cjk drastic          # ← 重命名 + 替换，这一步不能省
chmod 755 drastic               # 对齐原版的 -rwxr-xr-x
```

**权限是必须的**：直接 `scp` 上去的文件权限可能是 `644`，少了执行位启动就会失败；
`chmod 755` 与原来的 `-rwxr-xr-x` 对齐。

> 也可以一步到位（主机端直接改成目标名字再传）：
> ```sh
> scp build/drastic.cjk root@<device>:/storage/.config/drastic/drastic
> ssh root@<device> "chmod 755 /storage/.config/drastic/drastic"
> ```
> 但这样会**直接覆盖原版、且没有备份**，不推荐首次部署时使用。

设备上验证版本：

```sh
md5sum /storage/.config/drastic/drastic
# 373b50bfde2112438b37c968073ff853
```

然后**运行模拟器**，呼出菜单确认中文显示。若菜单正常且游戏能正常启动，说明注入层
安全；若一呼菜单就退出，多半是 payload 里混进了绝对地址（`patch.py` 的第 2 步会
提前拦住这种情况）。

---

## 5. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `assert elf_bss(...) == 0x1681a0` 失败 | `DRASTIC_SRC` 指向的不是目标版本 | 核对 md5 |
| `payload outgrew its 8 KB slot` | `cjk.c` 改动后代码段超了 | 精简代码，或参考 `INTERNALS.md` 的空间预算 |
| `absolute address 0x... stashed at VA 0x...` | 往 payload 里放了函数指针/字符串指针表 | 改成数组或相对偏移；PC 相对引用是安全的 |
| `payload is missing symbol cjk_entry` | `link.ld` 没保留符号表，或函数名改了 | 检查 `link.ld` 与 `entry.S` |
| `no zig found` | 没装 zig | `pip install ziglang`，或 `export ZIG=/path/to/zig` |
| 设备上启动即失败 | 少了执行位 | `chmod 755` |
| 菜单中文是方框 | 该字不在 GB2312 内 | 见"增删词条" |
| 重新生成资源后 md5 变了 | 换了 Unifont 上游版本，或改了降采样阈值/加粗 | 见下节"可复现性" |

---

## 6. 改翻译 / 增删菜单项

翻译表在 `tools/genmenu.py` 顶部的 `E` 列表里，每行是
`(原版字符串地址, 排版类型, 原文字, 中文)`。

```python
(0x121EF8, 'L', "Change Options",  "更改选项"),
```

排版类型决定补空格的方式 —— 原版渲染器**按字符个数**算高亮框宽度和数值列位置，
所以替换串必须保持**渲染后的格数不变**：

| 类型 | 含义 | 补空格方式 |
|---|---|---|
| `L` | 字段标签 | 保留左缩进，右侧补空格 |
| `R` | 右对齐数值 | 保留右边界，左侧补空格 |
| `P6` | 6×10 小字号串 | 按像素宽度换算，末尾补空格 |
| `X` | printf 参数 | 不补（如 `enabled`/`disabled`） |

一个中文字 = 1 格（我们注入的字模步进正好等于格宽），一个 ASCII 字节 = 1 格。

改完之后:

```sh
export DRASTIC_SRC=/path/to/drastic
python3 tools/genmenu.py        # 会逐条 assert 原文是否匹配
./build.sh
```

`genmenu.py` 会**逐条校验**你写的"原文字"和原版二进制里的实际内容是否一致，
不一致直接报错 —— 这样翻译表不会在版本漂移后悄悄错位。

### 增删整个菜单项

菜单行表 `ROWTAB` 是**从厂商自己的菜单树里反推出来的**，不是手写的：

```sh
pip install unicorn
cd harness && CJK=../../build/drastic.cjk python3 ../tools/gen_rowtab.py > /tmp/rowtab.inc
```

把输出替换掉 `src/cjk.c` 里 `static const rowdef_t ROWTAB[]` 的内容
（并同步 `ROWTAB_N`）。详见 `harness/README.md`。

---

## 7. 改字体

```sh
export DRASTIC_SRC=/path/to/drastic
./gen-assets.sh
```

`gen-assets.sh` 依次跑 `genmenu.py`、`genfont5.py`、`genfont6.py`、
`genfont_uni.py`，重写 `assets/` 下 7 个文件（`unifont.hex` 不在其列，
它只在换上游版本时才需要重裁）。

字体来自 **GNU Unifont** 的 16×16 原生位图（`assets/unifont.hex`，
GB2312 子集），按宿主字体高度分四套：

| 文件 | 尺寸 | 来源 |
|---|---|---|
| `font_15.bin` | 15×15 | 16→15，箱式滤波，阈值 0.50，几乎 1:1 |
| `font_10.bin` | 10×10 | 16→10，阈值 0.30 |
| `font_8.bin` | 8×8 | 16→8，**源先加粗 1 px**，阈值 0.30，整体下移一行对齐基线 |
| `font_16.bin` | 16×16 | 上游 16×16 位图直接拷贝，不做任何加工 |
| `uni_tab.bin` | — | GB2312 → Unicode 映射，纯算法，与字体无关 |

8×8 那套的加粗不是装饰：Unifont 的笔画恰好 1 px 宽，16→8 时一根横画只覆盖
输出像素的 1/4，不先加粗就会整笔丢掉（「称」「戏」这类字直接消失）。
16×16 那套反过来**不能**加粗 —— 16 px 下笔画已到位，加粗会把字糊成一团。

换上游版本：

```sh
# 从 https://ftp.gnu.org/gnu/unifont/ 或镜像取 unifont-<ver>.tar.gz
UNIFONT_HEX=/path/to/unifont_all-<ver>.hex python3 tools/unifont_subset.py
./gen-assets.sh
```

`unifont.py` 会在 `assets/unifont.hex` 缺失时报错并提示这一步。
许可与上游校验值见 [../assets/README.md](../assets/README.md)。

> ⚠️ `genfont5.py` 里 `pack()` 写的 8 字节文件头是**字形数量**而不是字宽字高。
> 这是个历史遗留的笔误，但**不能"修"** —— 注入层编译期就把几何尺寸写死了
> （`SZ15/SZ10/SZ8`），根本不读这个头；改成 `(N,N)` 只会让 `font_15/10/8.bin`
> 字节变化，从而让整个构建的 md5 变化。代码里有注释标注。

---

## 8. 可复现性核对

```sh
git clone <repo> && cd drastic-cjk
export DRASTIC_SRC=/path/to/drastic
./build.sh
python3 tools/verify.py build/drastic.cjk
```

期望：

```
md5 373b50bfde2112438b37c968073ff853
size 2 403 166
== the reference build, byte for byte
```

两处都可能引入不可复现：

1. **字体来源** —— `assets/unifont.hex` 是上游 Unifont 的裁剪拷贝，已提交，
   所以正常构建**完全不依赖**任何外部字体；只有重跑 `unifont_subset.py`
   （换了上游版本）或改降采样参数，产物才会变。
2. **工具链版本** —— zig 0.16.0 已验证；换大版本可能改变代码生成，进而改变
   payload 字节和最终 md5。改了就在 `docs/INTERNALS.md` 里记一笔。

---

## 附录：相关的 UI 资源

菜单左上角那张 "DraStic" 图**不在**可执行文件里，是运行时从模拟器目录读取的
外部裸位图：

```
<drastic 目录>/drastic_logo_0.raw
<drastic 目录>/drastic_logo_1.raw
```

400×150、小端 u16、RGB565、**无文件头**、恰好 120 000 字节；用哪个文件由
`time(NULL) & 1` 决定，所以**两份都要换**。`fread` 读不满 120 000 字节时整张图被
跳过（不会崩）。想改这张图不需要动可执行文件。
