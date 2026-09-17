# claude-or

Run [Claude Code](https://docs.anthropic.com/en/docs/claude-code) on **free** models from [OpenRouter](https://openrouter.ai), [AIHubMix](https://aihubmix.com), or [ZenMux](https://zenmux.ai) — without hijacking your Anthropic login.

Your regular `claude` command stays on your subscription. Each provider is a separate Claude Code profile. Claude Code can only talk to **one** gateway per session, so `claude-or use` switches profiles instead of merging `/model` lists.

中文说明在下面。

## Why this exists

The usual setup is:

```bash
export ANTHROPIC_BASE_URL="https://openrouter.ai/api"
export ANTHROPIC_AUTH_TOKEN="$OPENROUTER_API_KEY"
```

That replaces **every** Claude Code session. If you already pay for Claude, you lose it.

`claude-or` sets `CLAUDE_CONFIG_DIR` to a per-provider directory (`~/.claude-openrouter`, `~/.claude-or-aihubmix`, or `~/.claude-or-zenmux`) for one process. Two logins, no fighting over Keychain. `claude-or status` prints the live config dir and Keychain service.

It also rebuilds `/model` from OpenRouter’s live catalog:

- `:free` models
- `$0` models with no `:free` suffix (`stealth/union-alpha` is the current example)
- skip anything that cannot drive Claude Code (no tool calling, audio-only, non-text)
- probe OpenRouter **endpoints** (uptime/status, not a chat completion) and pin dead models to the bottom as `Down · …`
- show remaining free-model requests from `GET /api/v1/key` (`claude-or status` / `doctor`, and a one-liner when you launch)

## Install

You need [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and Python 3.

```bash
git clone https://github.com/saga7878/claude-or.git
cd claude-or
./install.sh
```

That symlinks `~/.local/bin/claude-or`. Then:

```bash
claude-or providers
claude-or use openrouter   # default
claude-or key              # stores that provider's key (Keychain on macOS)
claude-or                  # syncs the catalog on first run, then launches
```

```bash
claude-or use aihubmix && claude-or key    # https://aihubmix.com
claude-or use zenmux && claude-or key      # https://zenmux.ai
```

Inside the session, `/model` is the free list. Stealth models show up as `Stealth · …` (or `匿名 · …` when `LANG` starts with `zh`).

```bash
claude-or --model stealth/union-alpha
claude-or sync      # catalog + liveness; does not spend the 50/day chat quota
claude-or status    # up/down counts and 38/50 free req left today
claude-or doctor
claude-or web       # local dashboard at http://127.0.0.1:8787
```

`claude-or web` binds **loopback only**. Use it to switch the next-launch provider, pin default models, store a key, refresh the catalog, and read OpenRouter’s remaining free requests. It does **not** remote-control a Claude Code session that is already running — one process still has one `ANTHROPIC_BASE_URL`. `--host 0.0.0.0` is refused.

A catalog older than 24 hours is refreshed on the next `claude-or` launch. `sync --no-probe` skips the endpoint checks.

Do **not** put `ANTHROPIC_BASE_URL` in `~/.zshrc`.

## Limits

- Claude Code has one `ANTHROPIC_BASE_URL` per process. Mixing OpenRouter + AIHubMix + ZenMux in the same `/model` picker would need a local proxy; this tool does not do that. `claude-or web` is a next-launch control plane, not a remote control for a live session.
- OpenRouter free endpoints are rate-limited (commonly 20 req/min and 50 req/day; 1000/day after a one-time $10 credit purchase). Claude Code burns requests fast. AIHubMix / ZenMux publish their own per-model caps.
- Endpoint probing (uptime/status, no chat quota) is OpenRouter-only. Other providers sync the catalog without a live ping.
- Third-party free models can drop tools, thinking, or long agent loops. Stealth models may retain prompts.

## Uninstall

```bash
rm ~/.local/bin/claude-or
rm -rf ~/.claude-openrouter ~/.claude-or-aihubmix ~/.claude-or-zenmux ~/.claude-or
# optional:
# security delete-generic-password -s openrouter -a api-key
# security delete-generic-password -s aihubmix -a api-key
# security delete-generic-password -s zenmux -a api-key
```

---

## 中文

用 OpenRouter 的免费模型跑 Claude Code，**不动**你原来的 `claude` 订阅登录。

匿名 stealth 模型往往没有 `:free` 后缀，但定价是 0。当前例子：`stealth/union-alpha`。`claude-or sync` 会把这类模型顶到 `/model` 前面，显示为 `匿名 · Union Alpha`。挂掉的模型沉到名单底部，标成 `挂了 · …`。`status` 会显示今天还剩多少免费请求。

AIHubMix / ZenMux 用独立 profile，不要和 OpenRouter 混在同一次会话里：

```bash
claude-or use aihubmix
claude-or key
claude-or
```

```bash
git clone https://github.com/saga7878/claude-or.git
cd claude-or
./install.sh
claude-or key
claude-or
```

```bash
claude-or web
```

本机页面：`http://127.0.0.1:8787`。用来切下次要用的网关、改默认模型、看 OpenRouter 剩余次数。已经开着的 Claude Code **不会**跟着换。不监听局域网。

不要把 `ANTHROPIC_BASE_URL` 写进 shell 配置，否则所有 `claude` 会话都会被抢走。
