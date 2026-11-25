FROM ubuntu:24.04@sha256:562111b88caa79c71391c0c4d3c2114a7d5c35915c20561fd893cb1e07929e6b
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    build-essential cmake pkg-config git ca-certificates curl python3 python3-venv python3-dev \
    libssl-dev libzmq3-dev libunbound-dev libsodium-dev libunwind-dev \
    libreadline-dev libhidapi-dev libusb-1.0-0-dev libprotobuf-dev \
    protobuf-compiler libboost-chrono-dev libboost-date-time-dev \
    libboost-filesystem-dev libboost-locale-dev libboost-program-options-dev \
    libboost-regex-dev libboost-serialization-dev libboost-system-dev \
    libboost-thread-dev libexpat1-dev libclang-common-18-dev \
    && rm -rf /var/lib/apt/lists/*
ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo PATH=/opt/cargo/bin:$PATH
RUN curl -sSf --proto '=https' --tlsv1.2 https://sh.rustup.rs | sh -s -- -y -q --profile minimal --default-toolchain 1.85.0 \
    && chmod -R a+rX /opt/rustup /opt/cargo
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install -q --no-deps --require-hashes -r /tmp/requirements.txt
# The parsers trailmark loads are fetched by the language pack at first use.
# Fetch them here, where the network is allowed, and pin the bundle.
ENV TREE_SITTER_LANGUAGE_PACK_CACHE_DIR=/opt/tslp
RUN /opt/venv/bin/python -I -c 'import tree_sitter_language_pack as t; t.download(["c", "cpp", "rust", "json", "python", "toml"])' \
    && echo "edcf1bc5546f263fadfd59e648ecb06023875eee164262bb41a805e0267a0b10  $(ls /opt/tslp/*/*/bundles/linux-x86_64-*.tar.zst)" | sha256sum -c - \
    && chmod -R a+rX /opt/tslp
# Trailmark compiles its bundled Rust grammar on first use, into its own
# install directory: do it here, where that directory is writable.
RUN mkdir /tmp/warm && echo 'fn f() { g(); } fn g() {}' > /tmp/warm/a.rs \
    && /opt/venv/bin/python -I -c 'from trailmark.query.api import QueryEngine; QueryEngine.from_directory("/tmp/warm", language="rust")' 2>&1 | tee /tmp/warm.log \
    && ! grep -q "Could not load" /tmp/warm.log && rm -rf /tmp/warm /tmp/warm.log && chmod -R a+rX /opt/venv
