#!/bin/zsh
set -euo pipefail

script_dir="${0:A:h}"
bin_dir="${HOME}/bin"

mkdir -p "$bin_dir"

cat > "${bin_dir}/scai" <<EOF
#!/bin/zsh
SCAI_PROG=scai exec python3 "${script_dir}/scai.py" "\$@"
EOF

cat > "${bin_dir}/bf" <<EOF
#!/bin/zsh
SCAI_PROG=bf exec python3 "${script_dir}/scai.py" "\$@"
EOF

cat > "${bin_dir}/scan" <<EOF
#!/bin/zsh
SCAI_PROG=scan exec python3 "${script_dir}/scai.py" "\$@"
EOF

chmod +x "${bin_dir}/scai" "${bin_dir}/bf" "${bin_dir}/scan"

echo "已安装 scai: ${bin_dir}/scai"
echo "旧别名 bf: ${bin_dir}/bf"
echo "表格兼容入口 scan: ${bin_dir}/scan"
echo "运行 scai --help 查看用法。"
