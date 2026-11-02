#!/usr/bin/env bash
# Install the pinned cluster tools on a CI runner (k3d and kubectl) and free disk space.
set -euo pipefail
K3D_VERSION=v5.7.4
KUBECTL_VERSION=v1.34.1
sudo curl -sSLo /usr/local/bin/k3d "https://github.com/k3d-io/k3d/releases/download/${K3D_VERSION}/k3d-linux-amd64"
sudo curl -sSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
sudo chmod +x /usr/local/bin/k3d /usr/local/bin/kubectl
# the runner image ships SDKs we do not need; the teacher model and images need the space
sudo rm -rf /usr/share/dotnet /usr/local/lib/android /opt/ghc /opt/hostedtoolcache/CodeQL || true
k3d version
kubectl version --client
nproc
free -g
df -h /
