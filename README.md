# 投票系统

自动化投票脚本，支持多账号批量投票，使用代理和验证码识别服务。

## 项目结构

```
├── vote.py          # 主程序文件
├── config.yml       # 配置文件
├── requirements.txt # Python依赖包
└── README.md       # 说明文档
```

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置说明

编辑 `config.yml` 文件，配置以下参数：

### 必需配置
- `captcha.api_key`: 2captcha API密钥
- `proxy`: 代理服务器配置
- `accounts`: 要投票的账号列表

### 可选配置
- `execution.max_rounds`: 最大重试轮数（默认3轮）
- `execution.delay_between_accounts`: 账号间延时范围
- `browser.user_agents`: 浏览器User-Agent列表
- `logging`: 日志配置

## 使用方法

1. 配置 `config.yml` 文件
2. 运行脚本：
   ```bash
   python vote.py
   ```

## 日志文件

程序运行时会生成 `vote_log_时间戳.log` 日志文件，记录详细的执行过程。

## 注意事项

- 确保代理服务正常工作
- 确保2captcha账户有足够余额
- 建议在测试环境先验证配置正确性 