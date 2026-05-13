#!/bin/bash
# NVIDIA Container Toolkit installation script
# Used to enable GPU support for Docker

set -e

echo "=========================================="
echo "NVIDIA Container Toolkit Installation Script"
echo "=========================================="
echo ""

# Check for NVIDIA GPU
echo "Step 1/6: Checking for NVIDIA GPU..."
if ! lspci | grep -i nvidia > /dev/null; then
    echo "❌ Error: NVIDIA GPU not detected"
    echo "Please ensure your system has an NVIDIA graphics card"
    exit 1
fi
echo "✓ NVIDIA GPU detected"
echo ""

# Check NVIDIA drivers
echo "Step 2/6: Checking NVIDIA drivers..."
if ! nvidia-smi > /dev/null 2>&1; then
    echo "❌ Error: NVIDIA drivers not installed or not configured correctly"
    echo "Please install NVIDIA drivers first: https://www.nvidia.com/Download/index.aspx"
    exit 1
fi
echo "✓ NVIDIA drivers are installed"
nvidia-smi
echo ""

# Detect system type
echo "Step 3/6: Detecting system type..."
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VERSION_ID=$VERSION_ID
    echo "✓ System detected: $OS $VERSION_ID"
else
    echo "❌ Error: Unable to detect system type"
    exit 1
fi
echo ""

# Add NVIDIA Container Toolkit repository
echo "Step 4/6: Adding NVIDIA Container Toolkit repository..."
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)

# Add GPG key
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
    sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

# Add repository
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

echo "✓ Repository added successfully"
echo ""

# Install NVIDIA Container Toolkit
echo "Step 5/6: Installing NVIDIA Container Toolkit..."
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
echo "✓ NVIDIA Container Toolkit installed successfully"
echo ""

# Configure Docker
echo "Step 6/6: Configuring Docker to use NVIDIA Runtime..."
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
echo "✓ Docker configuration complete"
echo ""

# Verify installation
echo "=========================================="
echo "Verifying GPU support..."
echo "=========================================="
if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi > /dev/null 2>&1; then
    echo "✓ GPU support verified successfully!"
    echo ""
    echo "Docker can now use the GPU"
    docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
else
    echo "❌ GPU support verification failed"
    echo "Please check logs and try again"
    exit 1
fi

echo ""
echo "=========================================="
echo "Installation complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Start Ollama GPU version:"
echo "   docker-compose up -d ollama"
echo ""
echo "2. Download model:"
echo "   docker exec -it threatrag-ollama ollama pull qwen2.5:7b"
echo ""
echo "3. Verify GPU usage:"
echo "   docker exec threatrag-ollama nvidia-smi"
echo ""

