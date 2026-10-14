# harness — Unicorn 验证工具

这些脚本把**打过补丁的二进制**直接加载进 Unicorn（用户态 AArch64 模拟器），
调用厂商自己的菜单构建器和行渲染器，把结果渲染成 PNG 或断言。它让"布局对不对"
变成可验证的事实，而不是靠肉眼在设备上比。

设备上跑一次成本很高，所以**大部分改动应该先在这里过**。

## 依赖

```sh
pip install unicorn pillow
```

还需要一个**已经打好补丁**的二进制（`CJK=` 指向它，默认 `../build/drastic.cjk`），
以及原版二进制（`DRASTIC_SRC`，`pltmap.py` 要用它解析 PLT 表）。

## 用法

```sh
cd drastic-cjk
export DRASTIC_SRC=/path/to/drastic

# 12 项不变量断言 —— 改完 cjk.c 之后必须全绿
python3 harness/test200.py

# 渲染某个页面，肉眼看布局
python3 harness/page_preview.py firm          # main / firm / keysx / opt / video / keys
python3 harness/page_preview.py all           # 全部页面
python3 harness/page_preview.py firm out.png  # 指定输出名

# 打印厂商菜单树的每一行（标签、y、渲染器地址）
python3 harness/menu_tree.py

# 记录某一页每一次 draw_text / fill_rect 调用（坐标级调试）
python3 harness/cjk_emit.py firm
```

常用环境变量：

| 变量 | 作用 |
|---|---|
| `CJK=` | 指定要模拟的二进制（默认 `build/drastic.cjk`） |
| `SEL=-1` | 取消选中态（`page_preview.py`） |
| `XO=88` | 覆写页面节点的 `+0x10` 字段，**模拟真机基址** |
| `NAME=Drastic` | 给编辑器行一个非空值（`test200.py` 默认设了） |
| `STRICT=1` | 只映射内核真正会映射的页，暴露越界访问 |

## 文件

| 文件 | 作用 |
|---|---|
| `page_sim.py` | 核心：搭出模拟环境，拦截 PLT 桩，跑厂商代码 |
| `pltmap.py` | 解析原版的 PLT → GOT → 符号名映射 |
| `page_preview.py` | 渲染页面成 PNG |
| `menu_tree.py` | 遍历厂商菜单树 |
| `cjk_emit.py` | 记录所有绘制调用 |
| `test200.py` | 12 项回归断言 |
| `ROWTAB` 生成器 | 在 `../tools/gen_rowtab.py` |

## ⚠️ 一个必须记住的局限

harness 把模块加载在 **VA 0**，而真机上 PIE 会被加载到别处。
依赖真实映射基址的常量**在这里测不出来** —— 早期版本就是这么翻车的：
色块判据用了 `x == 536`（harness 里页面节点的 `+0x10` 是 256），
真机上那个字段是 88，于是按 `x == 536` 判断的分支**一次都没命中**。

所以：

- 想在 harness 里复现真机行为，用 `XO=88`（`page_preview.draw_page` 会覆写该字段）
- 任何"只在真机成立"的常量，都不能只从这个模拟器里读出来。
  补充手段是**照片标定**：用照片里已知字数的整行标签量出像素比例，反解真机坐标。
  色块位置的最终定案就是这么得到的。

## 静态枚举的坑

用 capstone 扫描全程序找 xref 时**必须**开 `md.skipdata = True`，否则
`for ins in md.disasm(...)` 这个生成器会在数据段的非法指令处**静默中止**，
给出"0 命中"这种看起来很正常、实际完全错误的结果。
