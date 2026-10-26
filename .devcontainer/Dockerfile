FROM mcr.microsoft.com/devcontainers/python:3.12

RUN apt-get update \
    && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
        cm-super \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*


RUN curl -LsSf https://astral.sh/uv/install.sh \
    | UV_INSTALL_DIR=/usr/local/bin sh

ENV UV_LINK_MODE=copy

USER vscode
