# 手动迁移配置指南

本文件用于指导您在将此项目迁移到新电脑，并成功运行 `install.bat` 脚本**之后**，需要手动修改的关键配置项。

---

### **背景**

本项目的 Python 环境路径和桌面客户端 (`alas.exe`) 内部的路径在安装时是根据您电脑的当前环境决定的。因此，在迁移到新电脑后，这些路径很可能发生变化，需要手动更新。

---

### **步骤 1: 查找 Conda 环境路径**

在开始修改前，您必须先找到 `alas` 环境在新电脑上的确切安装位置。

1.  打开 **Anaconda Prompt** 或一个普通的终端。
2.  运行以下命令：
    ```bash
    conda env list
    ```
3.  在输出的列表中，找到名为 `alas` 的环境，并**复制它所在的完整路径**。
    *   它看起来像 `C:\Users\YourName\.conda\envs\alas` 或者 `D:\Anaconda\envs\alas`。

---

### **步骤 2: 修改核心配置文件**

这是为了让项目在重新编译时能找到正确的 Python。

1.  打开文件: `config/deploy.yaml`
2.  找到 `PythonExecutable` 这一项。
3.  将其值修改为您在**步骤 1** 中复制的路径，并在末尾加上 `\python.exe`。

    **示例:**
    ```yaml
    # 修改前:
    PythonExecutable: C:\Users\OldUser\.conda\envs\alas\python.exe
    # 修改后:
    PythonExecutable: D:\Environment\Anaconda\envs\alas\python.exe
    ```

---

### **步骤 3: 修改启动脚本**

这是为了让 `.bat` 启动脚本能为 `alas.exe` 设置正确的运行环境。

1.  打开文件: `start_alas_correct.bat`
2.  找到 `set "ENV_ROOT=..."` 这一行。
3.  将其值修改为您在**步骤 1** 中复制的路径。
4.  (可选) 检查 `set "CONDA_ROOT=..."` 的路径是否也是您新电脑上 Anaconda 的主安装目录，如果不是，也一并修改。

    **示例:**
    ```batch
    REM 修改前:
    set "ENV_ROOT=C:\Users\OldUser\.conda\envs\alas"
    REM 修改后:
    set "ENV_ROOT=D:\Environment\Anaconda\envs\alas"
    ```

---

### **步骤 4: (强烈推荐) 重新编译桌面客户端**

为了让 `alas.exe` 内部包含的 Python 路径也更新，您需要重新编译一次。

1.  打开终端，`cd` 进入 `webapp` 目录。
2.  运行以下命令:
    ```bash
    yarn run compile
    ```

---

### **步骤 5: 启动程序**

完成以上所有修改后，您现在可以通过双击运行 `start_alas_correct.bat` 来正常启动 Alas 程序了。


## 上游等价实现优先

用户于2026-10-12确认这是一条通用维护规则：每次上游rebase，核对上游与本地的实际行为、安全门禁和配置兼容；上游已经等价实现或完整覆盖用户需求时，直接采用上游并删除重复本地代码、补丁及只验证旧实现的兼容测试。不能仅凭名称或代码相似判断等价。保留有意义的行为回归、用户独有需求及上游尚未覆盖的差异，记录覆盖的提交、删留理由与验证证据。

本工作区先在AzurLaneAutoScript-Original rebase并验证，以明确旧远端SHA的force-with-lease推送个人分支；保护生产配置与未提交变更后再同步AzurLaneAutoScript-Use。默认覆盖配置1（alas）和配置2（alas2），保留各自账号参数，最后核验实际运行及守护状态。

用户于2026-10-21进一步授权：账号照顾节点、维护前后与故障处理收尾顺带检查上游，发现更新即主动按上述流程跟进，无需逐次确认。检查合并到有实际任务的单次节点，避免无更新时高频唤醒模型；人工游戏和既有维修互斥仍优先。开发验证、推送、生产同步和各账号实际恢复分别记录，不能把仅更新开发分支说成全部生效。
