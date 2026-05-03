#!/bin/bash

# Socranki Build Script
# This script packages the addon into a .ankiaddon file for AnkiWeb.

echo "Cleaning up old builds..."
rm -f Socranki.ankiaddon
mkdir -p dist

echo "Copying production files..."
cp __init__.py config_ui.py config.json README.md LICENSE dist/

echo "Creating Socranki.ankiaddon..."
cd dist
zip -r ../Socranki.ankiaddon __init__.py config_ui.py config.json README.md LICENSE
cd ..

echo "Cleaning up..."
rm -rf dist

echo "Done! Socranki.ankiaddon is ready for upload."
