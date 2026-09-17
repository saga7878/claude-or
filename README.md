# claude-or

Run [Claude Code](https://docs.anthropic.com/en/docs/claude-code) on [OpenRouter](https://openrouter.ai) **free** models — including anonymous stealth models that are $0 **without** a `:free` suffix — without hijacking your Anthropic login.

Your regular `claude` command stays on your subscription. `claude-or` is a separate profile.

中文说明在下面。

## Why this exists

The usual setup is:

```bash
export ANTHROPIC_BASE_URL="https://openrouter.ai/api"
export ANTHROPIC_AUTH_TOKEN="$OPENROUTER_API_KEY"
```

That replaces **every** Claude Code session. If you already pay for Claude, you lose it.

`claude-or` sets `CLAUDE_CONFIG_DIR` to `~/.claude-openrouter` for one process. Two profiles, two logins, no fighting over Keychain.

It also rebuilds `/model` from OpenRouter’s live catalog:

- `:free` models
- `$0` models with no `:free` suffix (`stealth/union-alpha` is the current example)
- skip anything that cannot drive Claude Code (no tool calling, audio-only, non-text)

## Install

You need [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and Python 3.

```bash
git clone https://github.com/saga7878/claude-or.git
cd claude-or
./install.sh
```

That symlinks `~/.local/bin/claude-or`. Then:

```bash
claude-or key    # stores sk-or-… in macOS Keychain (or a 0600 file on Linux)
claude-or        # first run syncs the catalog, then launches Claude Code
```

Inside the session, `/model` is the free list. Stealth models show up as `Stealth · …` (or `匿名 · …` when `LANG` starts with `zh`).

```bash
claude-or --model stealth/union-alpha
claude-or sync      # free catalog rotates
claude-or status
claude-or doctor
```

Do **not** put `ANTHROPIC_BASE_URL` in `~/.zshrc`.

## Limits

- OpenRouter free endpoints are rate-limited (commonly 20 req/min and 50 req/day; 1000/day after a one-time $10 credit purchase). Claude Code burns requests fast.
- OpenRouter only guarantees Claude Code against Anthropic first-party models. Third-party free models can drop tools, thinking, or long agent loops.
- Stealth models are anonymous third-party previews. The upstream provider may retain prompts.

## Uninstall

```bash
rm ~/.local/bin/claude-or
rm -rf ~/.claude-openrouter
# optional: security delete-generic-password -s openrouter -a api-key
```

---

## 中文

用 OpenRouter 的免费模型跑 Claude Code，**不动**你原来的 `claude` 订阅登录。

匿名 stealth 模型往往没有 `:free` 后缀，但定价是 0。当前例子：`stealth/union-alpha`。`claude-or sync` 会把这类模型顶到 `/model` 前面，显示为 `匿名 · Union Alpha`。

```bash
git clone https://github.com/saga7878/claude-or.git
cd claude-or
./install.sh
claude-or key
claude-or
```

不要把 `ANTHROPIC_BASE_URL` 写进 shell 配置，否则所有 `claude` 会话都会被抢走。
