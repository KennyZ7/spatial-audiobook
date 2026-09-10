# 数据和素材来源

## SADIE II

Copyright 2018 University of York. 数据由 AudioLab 的 Cal Armstrong、Lewis Thresh、Gavin Kearney 等为 SADIE 项目制作。原始许可 Apache License 2.0，参见 https://www.apache.org/licenses/LICENSE-2.0 。

引用：Armstrong et al. “A Perceptual Evaluation of Individual and Non-Individual HRTFs: A Case Study of the SADIE II Database.” Applied Sciences 2018, 8(11), 2029. DOI https://doi.org/10.3390/app8112029 。

项目使用 H3/H4/H5 的48kHz、256tap SOFA数据。官方介绍：https://www.york.ac.uk/sadie-project/database.html 。分发镜像：https://sofacoustics.org/data/database/sadie/ 。各文件URL与SHA256写入 `data/hrtf/*.json`。首次安装下载；不把滤波器当作本项目原创数据。

## Kenney Impact Sounds

12个音效来自 https://kenney.nl/assets/impact-sounds ，Creative Commons CC0。原许可随安装保存在 `data/assets/KENNEY-LICENSE.txt`。安装时从官方ZIP提取并转换成48kHz单声道WAV；素材名称与源文件名称保存在 `scripts/setup_recorded.py`。

## 本项目程序合成素材

`scripts/setup_assets.py` 产生的14个音效/氛围素材以 CC0-1.0 提供，均明确标注“合成”，不是实地录音。生成算法、随机种子及参数随代码提供。

## 系统配音和用户上传

示例文字为本项目原创；Windows系统音色遵循设备及相关软件许可，仅用于本机演示。正式模型生成素材遵循对应服务条款。用户上传音频保留“用户上传”来源标记，不自动认定为CC0。
