#!/bin/sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SKILL_NAME="digikey-parts"

link_skill() {
  source_dir=$1
  link_path=$2
  mkdir -p "$(dirname "$link_path")"
  if [ -L "$link_path" ]; then
    current=$(readlink "$link_path")
    if [ "$current" = "$source_dir" ]; then
      return 0
    fi
    echo "Refusing to replace existing symlink: $link_path -> $current" >&2
    exit 1
  fi
  if [ -e "$link_path" ]; then
    echo "Refusing to replace existing path: $link_path" >&2
    exit 1
  fi
  ln -s "$source_dir" "$link_path"
}

choose_bin_dir() {
  if [ "${DKTOOLS_BIN_DIR:-}" ]; then
    printf "%s\n" "$DKTOOLS_BIN_DIR"
    return 0
  fi
  if [ -d /opt/homebrew/bin ] && [ -w /opt/homebrew/bin ]; then
    printf "%s\n" /opt/homebrew/bin
    return 0
  fi
  printf "%s\n" "$HOME/.local/bin"
}

write_wrapper() {
  bin_dir=$1
  wrapper="$bin_dir/dktools"
  mkdir -p "$bin_dir"
  if [ -e "$wrapper" ] && ! grep -q "DIGIKEY_SEARCH_TOOLS_HOME=" "$wrapper" 2>/dev/null; then
    echo "Refusing to replace existing dktools command: $wrapper" >&2
    exit 1
  fi
  tmp="$wrapper.tmp.$$"
  cat > "$tmp" <<EOF
#!/bin/sh
DIGIKEY_SEARCH_TOOLS_HOME="$REPO_ROOT"
export PYTHONPATH="\$DIGIKEY_SEARCH_TOOLS_HOME\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m digikey_tools "\$@"
EOF
  chmod +x "$tmp"
  mv "$tmp" "$wrapper"
}

link_skill "$REPO_ROOT/.agents/skills/$SKILL_NAME" "$HOME/.codex/skills/$SKILL_NAME"
link_skill "$REPO_ROOT/.agents/skills/$SKILL_NAME" "$HOME/.agents/skills/$SKILL_NAME"
link_skill "$REPO_ROOT/.claude/skills/$SKILL_NAME" "$HOME/.claude/skills/$SKILL_NAME"
BIN_DIR=$(choose_bin_dir)
write_wrapper "$BIN_DIR"

echo "Configured Codex skill: $HOME/.codex/skills/$SKILL_NAME"
echo "Configured repo/agent skill alias: $HOME/.agents/skills/$SKILL_NAME"
echo "Configured Claude Code skill: $HOME/.claude/skills/$SKILL_NAME"
echo "Configured dktools command: $BIN_DIR/dktools"
if ! command -v dktools >/dev/null 2>&1; then
  echo "Note: $BIN_DIR is not on PATH in this shell. Add it to PATH to use dktools directly." >&2
fi
