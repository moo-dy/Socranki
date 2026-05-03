from aqt import mw
from aqt.qt import *
import urllib.request
import urllib.error
import json

class ConfigDialog(QDialog):
    def __init__(self, addon_name, parent=None):
        super().__init__(parent)
        self.addon_name = addon_name
        self.setWindowTitle("Socranki Configuration")
        self.setMinimumWidth(450)
        
        # Apply a polished modern style
        self.setStyleSheet("""
            QDialog {
                background-color: #f8f9fa;
            }
            QLabel {
                font-size: 13px;
                color: #333;
            }
            QLineEdit, QComboBox {
                padding: 8px;
                border: 1px solid #ced4da;
                border-radius: 6px;
                background: #fff;
                color: #212529;
                font-size: 13px;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #212529;
                border: 1px solid #ced4da;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                min-height: 35px;
                padding-left: 10px;
                background-color: transparent;
            }
            QComboBox QAbstractItemView::item:selected {
                background-color: #007aff;
                color: #ffffff;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #007aff;
                color: #ffffff;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #007aff;
            }
            QPushButton {
                background-color: #007aff;
                color: white;
                border: none;
                padding: 10px 16px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #005bb5;
            }
            QPushButton:disabled {
                background-color: #a0c4ff;
            }
            #cancelButton {
                background-color: #e9ecef;
                color: #495057;
            }
            #cancelButton:hover {
                background-color: #dee2e6;
            }
        """)
        
        self.config = mw.addonManager.getConfig(self.addon_name) or {}
        
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # Header
        header = QLabel("AI Backend Setup")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #212529; margin-bottom: 5px;")
        layout.addWidget(header)
        
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Enter API Key (leave empty for local Ollama)")
        self.api_key_input.setText(self.config.get("api_key", ""))
        self.api_key_input.textChanged.connect(self.on_api_key_changed)
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        
        self.backend_label = QLabel("OLLAMA (Local)")
        self.backend_label.setStyleSheet("font-weight: bold; color: #007aff; font-size: 14px;")
        
        self.model_combo = QComboBox()
        self.model_combo.setView(QListView())
        self.model_combo.setPlaceholderText("Select a model...")
        
        self.custom_url_input = QLineEdit()
        self.custom_url_input.setPlaceholderText("Optional (e.g. https://openrouter.ai/api/v1/chat/completions)")
        self.custom_url_input.setText(self.config.get("custom_api_url", ""))
        
        self.interaction_combo = QComboBox()
        self.interaction_combo.setView(QListView())
        self.interaction_combo.addItem("Chit-Chat (Interactive)", "chit_chat")
        self.interaction_combo.addItem("One-Liner (Show Answer)", "one_liner")
        current_mode = self.config.get("interaction_mode", "chit_chat")
        index = self.interaction_combo.findData(current_mode)
        if index >= 0:
            self.interaction_combo.setCurrentIndex(index)
        
        self.auto_generate_cb = QCheckBox("Automatically generate question on reveal")
        self.auto_generate_cb.setChecked(self.config.get("auto_generate", False))
        
        self.language_input = QLineEdit()
        self.language_input.setPlaceholderText("e.g., 'English', 'French', or 'auto'")
        self.language_input.setText(self.config.get("target_language", "auto"))
        
        form_layout.addRow("Target Language:", self.language_input)
        form_layout.addRow("Auto-Generate:", self.auto_generate_cb)
        form_layout.addRow("Interaction:", self.interaction_combo)
        form_layout.addRow("API Key:", self.api_key_input)
        form_layout.addRow("Detected Type:", self.backend_label)
        form_layout.addRow("Custom URL:", self.custom_url_input)
        form_layout.addRow("Model:", self.model_combo)
        
        layout.addLayout(form_layout)
        
        self.refresh_btn = QPushButton("Detect & Fetch Models")
        self.refresh_btn.clicked.connect(self.fetch_models)
        layout.addWidget(self.refresh_btn)
        
        layout.addSpacing(10)
        
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self.save_config)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("cancelButton")
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
        
        self.current_backend = self.config.get("backend_type", "ollama")
        
        # Initial trigger to populate everything
        self.on_api_key_changed(self.api_key_input.text())
        
        saved_model = self.config.get("model_name", "")
        if saved_model:
            self.model_combo.addItem(saved_model)
            self.model_combo.setCurrentText(saved_model)

    def on_api_key_changed(self, text):
        text = text.strip()
        if not text:
            self.current_backend = "ollama"
        elif text.startswith("sk-"):
            self.current_backend = "openai"
        elif text.startswith("AIza"):
            self.current_backend = "gemini"
        else:
            self.current_backend = "openai" # Assume compatible endpoint if unknown format
            
        self.backend_label.setText(f"{self.current_backend.upper()}")

    def fetch_models(self):
        self.model_combo.clear()
        self.model_combo.addItem("Fetching models...")
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("Fetching...")
        
        api_key = self.api_key_input.text().strip()
        backend = self.current_backend
        custom_url = self.custom_url_input.text().strip()
        
        def do_fetch():
            try:
                if backend == "ollama":
                    req = urllib.request.Request("http://localhost:11434/api/tags")
                    with urllib.request.urlopen(req, timeout=5) as response:
                        data = json.loads(response.read())
                        return [m["name"] for m in data.get("models", [])]
                        
                elif backend == "openai":
                    if custom_url:
                        url = custom_url.replace("/chat/completions", "/models")
                    else:
                        url = "https://api.openai.com/v1/models"
                    
                    req = urllib.request.Request(url)
                    req.add_header("Authorization", f"Bearer {api_key}")
                    with urllib.request.urlopen(req, timeout=10) as response:
                        data = json.loads(response.read())
                        models = [m["id"] for m in data.get("data", [])]
                        if not custom_url:
                            # Filter OpenAI list down to relevant models
                            models = [m for m in models if "gpt" in m or "o1" in m or "o3" in m]
                        models.sort()
                        return models
                        
                elif backend == "gemini":
                    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}")
                    with urllib.request.urlopen(req, timeout=10) as response:
                        data = json.loads(response.read())
                        return [m["name"].replace("models/", "") for m in data.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
            except Exception as e:
                return [f"Error: {str(e)}"]
            
            return []

        def on_done(future):
            self.model_combo.clear()
            self.refresh_btn.setEnabled(True)
            self.refresh_btn.setText("Detect & Fetch Models")
            
            try:
                models = future.result()
                if not models:
                    self.model_combo.addItem("No models found")
                else:
                    for m in models:
                        self.model_combo.addItem(m)
                
                saved_model = self.config.get("model_name", "")
                index = self.model_combo.findText(saved_model)
                if index >= 0:
                    self.model_combo.setCurrentIndex(index)
            except Exception as e:
                self.model_combo.addItem(f"Exception: {str(e)}")

        mw.taskman.run_in_background(do_fetch, on_done)

    def save_config(self):
        self.config["api_key"] = self.api_key_input.text().strip()
        self.config["backend_type"] = self.current_backend
        self.config["model_name"] = self.model_combo.currentText().strip()
        self.config["interaction_mode"] = self.interaction_combo.currentData()
        self.config["auto_generate"] = self.auto_generate_cb.isChecked()
        self.config["target_language"] = self.language_input.text().strip()
        if self.config["model_name"].startswith("Error:") or self.config["model_name"] == "Fetching models...":
            self.config["model_name"] = ""
        self.config["custom_api_url"] = self.custom_url_input.text().strip()
        
        mw.addonManager.writeConfig(self.addon_name, self.config)
        self.accept()
