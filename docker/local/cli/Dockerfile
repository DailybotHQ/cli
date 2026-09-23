# Dailybot Core CLI Development Container
# Base image with Python 3.14 + Node.js 24 for documentation and coordination work
FROM python:3.14.4-slim-trixie

LABEL maintainer="developers@dailybot.com"

# Run every RUN under bash with `pipefail`. Docker's default `sh -c` has no
# pipefail, so in a `curl … | bash` pipeline the exit status is bash's, not curl's:
# a failing curl writes nothing to stdout, bash reads an empty script and exits 0,
# and the image builds with the tool MISSING — silently. This stage pipes curl into
# bash/dd several times (nodesource, gh keyring, claude, cursor), so the directive
# goes here, before the first RUN. (Docker best practice; hadolint DL4006.)
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# One apt layer for this image. Later RUN steps must not call apt-get update.
# python:slim has no curl, so this RUN cannot fetch a keyring first.
# mu-vim's install.lua may still update if a package is missing; listing its
# known packages here makes that update a no-op.
# Do not install the neovim apt package: remoteUser gets the official tarball.
# gh is the official release tarball below. Debian trixie's sqv rejects the
# GitHub CLI apt repo key.
RUN apt-get update && apt-get install --no-install-recommends -y \
    # Essential tools
    sudo git bash-completion nano ssh openssh-server curl gnupg ca-certificates \
    # Build tools (for native npm packages)
    build-essential \
    # mu-vim / editor helpers (lua5.4 runs install.lua; rg and fd are required)
    lua5.4 ripgrep fd-find \
    python3-neovim luarocks \
    unzip tar xz-utils \
    # Clean up
    && ln -sf "$(command -v fdfind)" /usr/local/bin/fd \
    && update-alternatives --install /usr/local/bin/lua lua /usr/bin/lua5.4 100 \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    # SSH into this container: runtime dir only. Host keys are NOT generated
    # here: baking them puts the PRIVATE key in an image layer, and mints new
    # ones on every rebuild, so every client that pinned the old one refuses to
    # connect until the developer clears it by hand. The entrypoint generates
    # them into the persisted volume instead. Anything openssh-server's own
    # postinst left behind is removed for the same reason.
    && mkdir -p /var/run/sshd \
    && rm -f /etc/ssh/ssh_host_*

# GitHub CLI from the official release tarball. The apt repo fails signature
# verification on Debian trixie (sqv). curl is already installed above.
ARG GH_VERSION=2.83.2
RUN GH_ARCH="$(dpkg --print-architecture)" \
    && curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${GH_ARCH}.tar.gz" -o /tmp/gh.tar.gz \
    && tar -xzf /tmp/gh.tar.gz -C /tmp \
    && install -m 0755 "/tmp/gh_${GH_VERSION}_linux_${GH_ARCH}/bin/gh" /usr/local/bin/gh \
    && rm -rf /tmp/gh.tar.gz "/tmp/gh_${GH_VERSION}_linux_${GH_ARCH}" \
    && gh --version \
    # Drop-in only — do not redefine Subsystem sftp (already in Debian sshd_config)
    && printf '%s\n' \
        'PasswordAuthentication no' \
        'PubkeyAuthentication yes' \
        'PermitRootLogin no' \
        'UsePAM yes' \
        'AllowTcpForwarding yes' \
        'AllowStreamLocalForwarding yes' \
        # A non-interactive `ssh host command` gets sshd's own minimal PATH: no
        # /etc/profile, no ~/.bashrc. Without this, `ssh <machine> herdr ...` —
        # which is how a Herdr client prepares and checks a remote — fails with
        # "command not found". SetEnv states the PATH explicitly, and states
        # ONLY the PATH: nothing here may carry a credential.
        'SetEnv PATH=/home/dev-user/.local/bin:/home/dev-user/.cursor/bin:/home/dev-user/.opencode/bin:/home/dev-user/.grok/bin:/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin' \
        > /etc/ssh/sshd_config.d/herdr.conf \
    && chmod 644 /etc/ssh/sshd_config.d/herdr.conf

# Create devcontainer user and add it to sudoers
RUN groupadd --gid 1000 dev-user \
    && useradd --uid 1000 --gid dev-user --shell /bin/bash --create-home dev-user \
    && echo dev-user ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/dev-user \
    && chmod 0440 /etc/sudoers.d/dev-user

# Install Node.js 24.x (system-wide; binaries usable by all users).
# nodesource's setup script updates the apt index itself. This is not a
# second Dockerfile apt-get update.
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install --no-install-recommends -y nodejs \
    && node --version && npm --version && npx --version \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# The CLIs installed by their own installers below land in these directories.
# PATH must name them before those RUN steps verify the binaries.
ENV PATH="/home/dev-user/.local/share/pnpm/bin:/home/dev-user/.local/bin:/home/dev-user/.cursor/bin:/home/dev-user/.opencode/bin:/home/dev-user/.grok/bin:${PATH}"

# ENV alone is not enough. A LOGIN shell (`bash -l`, which is what `docker exec`
# and most editors use) sources /etc/profile, and Debian's /etc/profile REPLACES
# PATH outright — the ENV above is silently discarded and OpenCode disappears.
# A profile.d drop-in re-adds the directories after that reset, so both login
# and non-login shells see the same set.
RUN printf '%s\n' \
        '# Added by the Dockerfile: /etc/profile resets PATH, so re-add the' \
        '# directories the AI CLI installers write into.' \
        'for d in "$HOME/.local/share/pnpm/bin" "$HOME/.local/bin" "$HOME/.cursor/bin" "$HOME/.opencode/bin" "$HOME/.grok/bin"; do' \
        '    case ":$PATH:" in' \
        '        *":$d:"*) ;;' \
        '        *) [ -d "$d" ] && PATH="$d:$PATH" ;;' \
        '    esac' \
        'done' \
        'export PATH' \
        > /etc/profile.d/10-dailybot-ai-clis.sh \
    && chmod 644 /etc/profile.d/10-dailybot-ai-clis.sh

# Install Dailybot CLI (system-wide; this RUN executes as root — the `USER dev-user`
# directive is further down — so pip drops the binary in /usr/local/bin/, available to
# dev-user). `-f` makes an HTTP error a non-zero curl exit instead of piping an error
# page into bash; the `SHELL … pipefail` above makes a failing curl abort the build.
# install.sh itself runs `set -euo pipefail`, so failures inside it abort too.
RUN curl -fsSL https://cli.dailybot.com/install.sh | DAILYBOT_VERSION='>=3.9.0' bash

# Install all Python dev/runtime deps from the repo's lock file.
# This single COPY/RUN pair is the only build cache layer pip touches — it
# invalidates ONLY when requirements/dev.txt changes, so day-to-day source
# edits don't slow down rebuilds.
#
# requirements/dev.txt is generated by `pip-compile pyproject.toml --extra=dev`
# (run via the `pip_update` shell helper in custom_commands.sh). Pinning to
# this lock means every container, every dev, every rebuild gets the same
# resolved versions of ruff, mypy, pytest, httpx, click, etc.
COPY requirements/dev.txt /tmp/requirements-dev.txt
RUN pip install --no-cache-dir -r /tmp/requirements-dev.txt \
    && rm /tmp/requirements-dev.txt

# python-semantic-release ships its own pinned (and rather aggressive) versions
# of click, rich, importlib-resources, etc. Installing it into the same Python
# env as the rest of the dev tools would downgrade those packages, holding the
# dev container behind what end users see when they `pip install dailybot-cli`.
# pipx isolates PSR in its own venv and exposes only the `semantic-release`
# binary on PATH — the user-visible behavior is the same, but click==8.3.x and
# rich==15.x stay in the main env. Auto-release.yml uses plain `pip install` in
# CI because that job has no other Python deps to protect.
RUN pip install --no-cache-dir pipx \
    && pipx install --global "python-semantic-release>=10,<11"

# Coding-agent CLIs. Each flag defaults false. Only the exact string "true"
# installs. A skipped flag is its own RUN so flipping one does not rebuild apt.
# Herdr is not one of these flags: the container still needs it to be a machine.
#
# Native installers follow $HOME. This image is still root here, so they would
# land in /root/.local/bin and `claudex` would report "command not found" for
# dev-user. npm -g stays as root: that binary is already on the default PATH.
ARG INSTALL_CLAUDE_CLI=false
ARG INSTALL_CURSOR_CLI=false
ARG INSTALL_CODEX_CLI=false
ARG INSTALL_PI_CLI=false
ARG INSTALL_OPENCODE_CLI=false
ARG INSTALL_CLINE_CLI=false
ARG INSTALL_GROK_CLI=false

# Pi is installed with --ignore-scripts: its postinstall fetches a platform
# binary that is not needed here and fails the build on some architectures.
RUN if [ "${INSTALL_CODEX_CLI}" = "true" ]; then npm install -g @openai/codex; else echo "INSTALL_CODEX_CLI is not true; skip"; fi
RUN if [ "${INSTALL_PI_CLI}" = "true" ]; then npm install -g --ignore-scripts @earendil-works/pi-coding-agent; else echo "INSTALL_PI_CLI is not true; skip"; fi
RUN if [ "${INSTALL_CLINE_CLI}" = "true" ]; then npm install -g cline; else echo "INSTALL_CLINE_CLI is not true; skip"; fi

USER dev-user
RUN if [ "${INSTALL_CLAUDE_CLI}" = "true" ]; then curl -fsSL https://claude.ai/install.sh | bash; else echo "INSTALL_CLAUDE_CLI is not true; skip"; fi \
    && if [ "${INSTALL_CLAUDE_CLI}" = "true" ]; then test -x /home/dev-user/.local/bin/claude; fi
RUN if [ "${INSTALL_CURSOR_CLI}" = "true" ]; then curl -fsSL https://cursor.com/install | bash; else echo "INSTALL_CURSOR_CLI is not true; skip"; fi
RUN if [ "${INSTALL_OPENCODE_CLI}" = "true" ]; then curl -fsSL https://opencode.ai/install | bash -s -- --no-modify-path; else echo "INSTALL_OPENCODE_CLI is not true; skip"; fi
RUN if [ "${INSTALL_GROK_CLI}" = "true" ]; then curl -fsSL https://x.ai/cli/install.sh | GROK_BIN_DIR=/home/dev-user/.local/bin GROK_CHANNEL=stable bash; else echo "INSTALL_GROK_CLI is not true; skip"; fi \
    && if [ "${INSTALL_GROK_CLI}" = "true" ]; then test -x /home/dev-user/.local/bin/grok; fi
USER root

# Default terminal editor. nvim is the user-local tarball, not the apt package.
ENV EDITOR=nvim
ENV VISUAL=nvim
ENV GIT_EDITOR=nvim

# Set working directory
WORKDIR /workspace

# Copy and setup entrypoint script
# Path is relative to the repo-root build context (see docker-compose.yaml).
COPY docker/local/cli/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r//' /entrypoint.sh \
    && chmod +x /entrypoint.sh

# Pre-create persistent data directories owned by dev-user
RUN mkdir -p /home/dev-user/.claude_data \
             /home/dev-user/.codex_data \
             /home/dev-user/.cursor_data \
             /home/dev-user/.cline_data \
             /home/dev-user/.opencode_data \
             /home/dev-user/.pi_data \
             /home/dev-user/.grok_data \
             /home/dev-user/.herdr_data \
             /home/dev-user/.gh_data \
             /home/dev-user/.dailybot_data \
             /home/dev-user/.ssh \
    && chown -R dev-user:dev-user /home/dev-user

# User-scoped git, herdr, and mu-vim. Coding CLIs above run only when flagged.
USER dev-user
RUN git config --global init.defaultBranch main \
    && git config --global pull.rebase false \
    && git config --global safe.directory '*' \
    && git config --global core.editor nvim \
    && echo 'source /workspace/docker/custom_commands.sh' >> /home/dev-user/.bashrc \
    && curl -fsSL https://herdr.dev/install.sh | bash \
    && mkdir -p /home/dev-user/.config/herdr \
    && printf '%s\n' \
        '# Seeded by the Dockerfile.' \
        '# A login shell: it reads /etc/profile.d and ~/.profile, which is where PATH' \
        '# picks up the agent CLIs. A non-login shell reads neither and they vanish.' \
        'onboarding = false' \
        '' \
        '[terminal]' \
        'default_shell = "/bin/bash"' \
        'shell_mode = "login"' \
        'new_cwd = "/workspace"' \
        '' \
        '[ui]' \
        'mouse_capture = true' \
        '' \
        '[experimental]' \
        'allow_nested = true' \
        > /home/dev-user/.config/herdr/config.toml \
    && herdr --version \
    && rm -rf /home/dev-user/.claude /home/dev-user/.claude.json
USER root
# Herdr's Mac client starts the remote server over a non-login SSH session.
# That PATH is only /usr/local/bin:/usr/bin:/bin, so ~/.local/bin/herdr is
# invisible and the client stays on "reconnecting".
RUN ln -sfn /home/dev-user/.local/bin/herdr /usr/local/bin/herdr
USER dev-user

# Official Neovim 0.11.4 into ~/.local, ahead of any apt nvim the installer
# may add. ~/.local/bin is already first on PATH.
ARG NVIM_VERSION=0.12.5
RUN ARCH="$(uname -m)" \
    && case "$ARCH" in \
         x86_64) NVIM_ARCH=x86_64 ;; \
         aarch64|arm64) NVIM_ARCH=arm64 ;; \
         *) echo "unsupported arch for neovim: ${ARCH}" >&2; exit 1 ;; \
       esac \
    && curl -fsSL \
         "https://github.com/neovim/neovim/releases/download/v${NVIM_VERSION}/nvim-linux-${NVIM_ARCH}.tar.gz" \
         -o /tmp/nvim.tar.gz \
    && mkdir -p /home/dev-user/.local/bin \
    && tar -xzf /tmp/nvim.tar.gz -C /home/dev-user/.local \
    && ln -sfn "/home/dev-user/.local/nvim-linux-${NVIM_ARCH}/bin/nvim" /home/dev-user/.local/bin/nvim \
    && rm -f /tmp/nvim.tar.gz \
    && test "$(command -v nvim)" = /home/dev-user/.local/bin/nvim \
    && nvim --version | head -n 1 | grep -q "${NVIM_VERSION}"

# Pin Dailybot mu-vim. A tag or a full commit. Changing this busts the clone
# layer, so the next rebuild installs that release instead of a cached main.
ARG MU_VIM_REF=v0.7.0
# Full Dailybot mu-vim. install.lua prompts: custom directory No, extras blank
# (keeps the checked defaults). Drive those answers on stdin. Passwordless sudo
# is already in place so the script's sudo -v succeeds. Plugin sync must finish
# inside the image: +Pckr sync exits before clones land.
RUN GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
    git clone https://github.com/DailybotHQ/mu-vim.git /home/dev-user/.config/nvim \
    && cd /home/dev-user/.config/nvim \
    && git checkout --detach "${MU_VIM_REF}" \
    && test "$(git describe --tags --exact-match HEAD)" = "${MU_VIM_REF}" \
    && printf 'n\n\n' | lua install.lua \
    && test -f /home/dev-user/.config/nvim/init.lua \
    && test -f /home/dev-user/.local/share/nvim/mu-vim-installed \
    && test -d /home/dev-user/.local/share/nvim/pckr/pckr.nvim \
    && GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
       nvim --headless "+lua require('pckr.actions').sync()" "+sleep 120" "+qa!" \
    && python3 -c 'import os,sys; pack=os.path.expanduser("~/.local/share/nvim/site/pack/pckr/opt"); required=("alpha-nvim","nvim-cmp","mason.nvim"); missing=[]; \
assert os.path.isdir(pack), "pckr opt dir missing: "+pack; \
[(missing.append(name) if not [e for e in os.listdir(os.path.join(pack,name)) if e!=".git"] else None) for name in sorted(os.listdir(pack)) if os.path.isdir(os.path.join(pack,name))]; \
[missing.append(name+" (absent)") for name in required if not os.path.isdir(os.path.join(pack,name))]; \
sys.exit("plugin sync left empty clones: "+", ".join(missing)) if missing else print("plugin sync complete")' \
    && test "$(command -v nvim)" = /home/dev-user/.local/bin/nvim
USER root

ENTRYPOINT ["/entrypoint.sh"]
