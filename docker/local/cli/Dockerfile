# Dailybot Core CLI Development Container
# Base image with Python 3.14 + Node.js 24 for documentation and coordination work
FROM python:3.14.4-slim-trixie

LABEL maintainer="developers@dailybot.com"

# Install base system dependencies
RUN apt-get update && apt-get install --no-install-recommends -y \
    # Essential tools
    sudo git bash-completion nano ssh curl gnupg ca-certificates \
    # Build tools (for native npm packages)
    build-essential \
    # Clean up
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create devcontainer user and add it to sudoers
RUN groupadd --gid 1000 dev-user \
    && useradd --uid 1000 --gid dev-user --shell /bin/bash --create-home dev-user \
    && echo dev-user ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/dev-user \
    && chmod 0440 /etc/sudoers.d/dev-user

# Install Node.js 24.x (system-wide; binaries usable by all users)
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install --no-install-recommends -y nodejs \
    && node --version && npm --version && npx --version \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI (system-wide via apt; usable by all users)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install --no-install-recommends -y gh \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Dailybot CLI (system-wide; pip drops the binary in /usr/local/bin/, available to dev-user)
RUN curl -sSL https://cli.dailybot.com/install.sh | bash

# Install Codex CLI (system-wide via npm -g, available to dev-user)
RUN npm install -g @openai/codex

# Default terminal editor (used by Git for merge/commit messages in minimal environments)
ENV EDITOR=nano
ENV VISUAL=nano
ENV GIT_EDITOR=nano

# Set working directory
WORKDIR /workspace

# Copy and setup entrypoint script
COPY cli/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r//' /entrypoint.sh \
    && chmod +x /entrypoint.sh

# Pre-create persistent data directories owned by dev-user
RUN mkdir -p /home/dev-user/.claude_data \
             /home/dev-user/.codex_data \
             /home/dev-user/.cursor_data \
             /home/dev-user/.gh_data \
             /home/dev-user/.dailybot_data \
             /home/dev-user/.ssh \
    && chown -R dev-user:dev-user /home/dev-user

# All user-scoped configuration (git, bashrc, user-local CLIs) happens
# only for dev-user. Claude Code and Cursor CLIs are installed via their
# native installers into /home/dev-user/.local/bin (no system-wide symlink).
USER dev-user
RUN git config --global init.defaultBranch main \
    && git config --global pull.rebase false \
    && git config --global safe.directory '*' \
    && git config --global core.editor nano \
    && echo 'source /workspace/docker/custom_commands.sh' >> /home/dev-user/.bashrc \
    && curl -fsSL https://claude.ai/install.sh | bash \
    && curl -fsSL https://cursor.com/install | bash \
    && rm -rf /home/dev-user/.claude /home/dev-user/.claude.json
USER root

ENTRYPOINT ["/entrypoint.sh"]
