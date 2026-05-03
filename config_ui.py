import json
import os
import urllib.request
import urllib.error
from aqt import mw
from aqt.qt import *

class ConfigDialog(QDialog):
    def __init__(self, addon_name, parent=None):
        super().__init__(parent)
        self.addon_name = addon_name
        self.config = mw.addonManager.getConfig(addon_name) or {}
        
        self.setWindowTitle("Socranki Configuration")
        self.setMinimumWidth(550)
        
        # Apply dark mode theme if Anki is in dark mode
        from aqt.theme import theme_manager
        self.is_dark = theme_manager.night_mode
        self.setup_styles()
        
        self.init_ui()
        
    def setup_styles(self):
        accent_color = "#007aff"
        if self.is_dark:
            self.setStyleSheet(f"""
                QDialog {{ background-color: #2c2c2c; color: #ffffff; }}
                QLabel {{ color: #e0e0e0; font-size: 13px; }}
                QLineEdit, QComboBox {{ 
                    background-color: #3d3d3d; 
                    color: #ffffff; 
                    border: 1px solid #555; 
                    padding: 8px; 
                    border-radius: 4px;
                }}
                QGroupBox {{
                    font-weight: bold;
                    border: 1px solid #555;
                    margin-top: 1.1em;
                    padding-top: 15px;
                    color: {accent_color};
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px 0 3px;
                }}
                QPushButton {{ 
                    background-color: {accent_color}; 
                    color: white; 
                    border: none; 
                    padding: 8px 15px; 
                    border-radius: 5px;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background-color: #0063d1; }}
                QPushButton:disabled {{ background-color: #444; color: #888; }}
                QPushButton#cancelButton {{ background-color: #444; }}
                QPushButton#cancelButton:hover {{ background-color: #555; }}
                QPushButton#helpButton {{
                    background-color: #444;
                    color: #bbb;
                    border-radius: 10px;
                    font-weight: bold;
                    font-size: 12px;
                    padding: 0;
                }}
                QPushButton#helpButton:hover {{ background-color: #555; color: white; }}
                QCheckBox {{ color: #e0e0e0; }}
            """)
        else:
            self.setStyleSheet(f"""
                QDialog {{ background-color: #f8f9fa; }}
                QLabel {{ color: #212529; font-size: 13px; }}
                QLineEdit, QComboBox {{ 
                    background-color: #ffffff; 
                    border: 1px solid #ced4da; 
                    padding: 8px; 
                    border-radius: 4px;
                }}
                QGroupBox {{
                    font-weight: bold;
                    border: 1px solid #ced4da;
                    margin-top: 1.1em;
                    padding-top: 15px;
                    color: {accent_color};
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px 0 3px;
                }}
                QPushButton {{ 
                    background-color: {accent_color}; 
                    color: white; 
                    border: none; 
                    padding: 8px 15px; 
                    border-radius: 5px;
                    font-weight: bold;
                }}
                QPushButton:disabled {{ background-color: #ccc; color: #666; }}
                QPushButton#cancelButton {{ background-color: #6c757d; }}
                QPushButton#helpButton {{
                    background-color: #e9ecef;
                    color: #495057;
                    border: 1px solid #ced4da;
                    border-radius: 10px;
                    font-weight: bold;
                    font-size: 12px;
                    padding: 0;
                }}
                QPushButton#helpButton:hover {{ background-color: #dee2e6; }}
            """)

    def create_help_btn(self, message):
        btn = QPushButton("?")
        btn.setObjectName("helpButton")
        btn.setFixedSize(20, 20)
        btn.setToolTip("Click for more info")
        btn.clicked.connect(lambda: QMessageBox.information(self, "About this setting", message))
        return btn

    def add_row_with_help(self, layout, label_text, widget, help_msg):
        row_layout = QHBoxLayout()
        row_layout.addWidget(widget, 1)
        row_layout.addWidget(self.create_help_btn(help_msg), 0)
        layout.addRow(label_text, row_layout)

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # 1. AI Backend Configuration Group
        backend_group = QGroupBox("AI Backend Configuration")
        backend_layout = QFormLayout()
        backend_layout.setSpacing(12)
        
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Paste your API key here...")
        self.api_key_input.setText(self.config.get("api_key", ""))
        self.api_key_input.textChanged.connect(self.on_api_key_changed)
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        
        self.custom_url_input = QLineEdit()
        self.custom_url_input.setPlaceholderText("Optional override URL")
        self.custom_url_input.setText(self.config.get("custom_api_url", ""))
        
        self.backend_label = QLabel("OLLAMA (Local)")
        self.backend_label.setStyleSheet("font-weight: bold; color: #007aff; font-size: 14px;")
        
        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setView(QListView())
        self.model_combo.setPlaceholderText("Select a model...")
        
        self.refresh_btn = QPushButton("Fetch Models")
        self.refresh_btn.clicked.connect(self.fetch_models)
        
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.refresh_btn, 0)
        
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(10, 40)
        self.font_size_spin.setValue(self.config.get("ui_font_size", 14))
        
        self.box_height_spin = QSpinBox()
        self.box_height_spin.setRange(100, 1000)
        self.box_height_spin.setSingleStep(50)
        self.box_height_spin.setValue(self.config.get("ui_box_height", 250))
        
        self.add_row_with_help(backend_layout, "API Key:", self.api_key_input, 
            "Required for OpenAI or Gemini. Leave empty if using Ollama locally.\n\n"
            "OpenAI keys start with 'sk-'.\nGemini keys are usually alphanumeric.")
            
        self.add_row_with_help(backend_layout, "Custom URL:", self.custom_url_input, 
            "Optional: If you use OpenRouter, a local proxy, or a specific API endpoint, paste it here.\n\n"
            "Example: https://openrouter.ai/api/v1/chat/completions")
            
        backend_layout.addRow("Detected Type:", self.backend_label)
        backend_layout.addRow("Model:", model_row)
        
        self.add_row_with_help(backend_layout, "Text Size:", self.font_size_spin, "Adjust the font size of the Socranki Q/A window.")
        self.add_row_with_help(backend_layout, "Box Height:", self.box_height_spin, "Adjust the default height of the Socranki dock widget in pixels.")
        
        backend_group.setLayout(backend_layout)
        layout.addWidget(backend_group)
        
        # 2. Behavior Preferences Group
        behavior_group = QGroupBox("Behavior Preferences")
        behavior_layout = QFormLayout()
        behavior_layout.setSpacing(12)
        
        self.interaction_combo = QComboBox()
        self.interaction_combo.setView(QListView())
        self.interaction_combo.addItem("Chit-Chat (Interactive)", "chit_chat")
        self.interaction_combo.addItem("One-Liner (Show Answer)", "one_liner")
        current_mode = self.config.get("interaction_mode", "chit_chat")
        index = self.interaction_combo.findData(current_mode)
        if index >= 0:
            self.interaction_combo.setCurrentIndex(index)
            
        self.language_input = QLineEdit()
        self.language_input.setPlaceholderText("'auto' or language name")
        self.language_input.setText(self.config.get("target_language", "auto"))
        
        self.auto_generate_cb = QCheckBox("Enabled")
        self.auto_generate_cb.setChecked(self.config.get("auto_generate", False))
        
        self.personality_input = QLineEdit()
        self.personality_input.setPlaceholderText("e.g. Socranki, funny, strict...")
        self.personality_input.setText(self.config.get("ai_personality", "Socranki"))
        self.personality_input.setMaxLength(250)
        
        self.enable_ai_tagging_cb = QCheckBox("Enable AI Tagging")
        self.enable_ai_tagging_cb.setChecked(self.config.get("enable_ai_tagging", False))
        
        self.add_row_with_help(behavior_layout, "Interaction Mode:", self.interaction_combo, 
            "Chit-Chat: Interactive chat where the AI evaluates your answer.\n\n"
            "One-Liner: Hidden answer mode where you click a button to reveal the ideal answer.")
            
        self.add_row_with_help(behavior_layout, "Target Language:", self.language_input, 
            "Set to 'auto' to match the card's language.\n\n"
            "Set to a specific language (e.g. 'French') to force the AI to respond in that language.")
            
        self.add_row_with_help(behavior_layout, "Auto-Generate:", self.auto_generate_cb, 
            "If enabled, Socranki starts generating the question as soon as you see the front of the card.\n\n"
            "This makes the experience feel much faster, as the AI is often ready before you even reveal the answer!")
            
        self.ai_tagging_row = QHBoxLayout()
        self.ai_tagging_row.addWidget(self.enable_ai_tagging_cb, 1)
        self.ai_tagging_row.addWidget(self.create_help_btn(
            "If enabled, the AI will evaluate your answers in Chit-Chat mode and automatically tag the card with either 'good_comprehension' or 'needs_comprehension'.\n\n"
            "Future questions will adapt in complexity based on these tags."
        ), 0)
        behavior_layout.addRow("AI Tagging:", self.ai_tagging_row)

        self.add_row_with_help(behavior_layout, "AI Personality:", self.personality_input, 
            "Describe how the AI should behave.\n\n"
            "Default is 'Socranki' (a helpful Socratic tutor). You can change it to 'Funny', 'Shakespearean', 'Strict Professor', etc.\n"
            "(Limit: 250 characters)")
        
        self.interaction_combo.currentIndexChanged.connect(self.on_interaction_changed)
        self.on_interaction_changed()
        
        behavior_group.setLayout(behavior_layout)
        layout.addWidget(behavior_group)
        
        layout.addSpacing(10)
        
        # Bottom Buttons
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
        self.on_api_key_changed(self.api_key_input.text())
        
        saved_model = self.config.get("model_name", "")
        if saved_model:
            self.model_combo.addItem(saved_model)
            self.model_combo.setCurrentText(saved_model)

    def on_interaction_changed(self):
        is_chit_chat = self.interaction_combo.currentData() == "chit_chat"
        self.enable_ai_tagging_cb.setEnabled(is_chit_chat)
        if not is_chit_chat:
            self.enable_ai_tagging_cb.setChecked(False)

    def on_api_key_changed(self, text):
        key = text.strip()
        if not key:
            self.current_backend = "ollama"
            self.backend_label.setText("OLLAMA (Local)")
        elif key.startswith("sk-ant-"):
            self.current_backend = "anthropic"
            self.backend_label.setText("ANTHROPIC (Claude)")
        elif key.startswith("sk-") or key.startswith("gsk_") or key.startswith("or-"):
            self.current_backend = "openai"
            self.backend_label.setText("OPENAI-Compatible (API)")
        else:
            self.current_backend = "gemini"
            self.backend_label.setText("GEMINI (API)")

    def fetch_models(self):
        self.model_combo.clear()
        self.model_combo.addItem("Fetching models...")
        self.model_combo.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        QApplication.processEvents()
        
        models = []
        try:
            if self.current_backend == "ollama":
                url = "http://localhost:11434/api/tags"
                with urllib.request.urlopen(url, timeout=5) as response:
                    data = json.loads(response.read().decode())
                    models = [m["name"] for m in data.get("models", [])]
            elif self.current_backend == "openai":
                custom_url = self.custom_url_input.text().strip()
                url = custom_url if custom_url else "https://api.openai.com/v1/models"
                headers = {"Authorization": f"Bearer {self.api_key_input.text()}"}
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode())
                    models = [m["id"] for m in data.get("data", [])]
                    models.sort()
            elif self.current_backend == "gemini":
                api_key = self.api_key_input.text().strip()
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
                try:
                    with urllib.request.urlopen(url, timeout=10) as response:
                        data = json.loads(response.read().decode())
                        models = [m["name"].replace("models/", "") for m in data.get("models", []) if "gemini" in m.get("name", "").lower()]
                except Exception:
                    models = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-1.0-pro"]
            elif self.current_backend == "anthropic":
                models = ["claude-3-5-sonnet-20240620", "claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"]
        except Exception as e:
            self.model_combo.clear()
            self.model_combo.addItem(f"Error: {str(e)}")
            self.model_combo.setEnabled(True)
            self.refresh_btn.setEnabled(True)
            return

        self.model_combo.clear()
        if models:
            self.model_combo.addItems(models)
        else:
            self.model_combo.addItem("No models found")
        self.model_combo.setEnabled(True)
        self.refresh_btn.setEnabled(True)

    def save_config(self):
        self.config["api_key"] = self.api_key_input.text().strip()
        self.config["backend_type"] = self.current_backend
        self.config["model_name"] = self.model_combo.currentText().strip()
        self.config["interaction_mode"] = self.interaction_combo.currentData()
        self.config["auto_generate"] = self.auto_generate_cb.isChecked()
        self.config["enable_ai_tagging"] = self.enable_ai_tagging_cb.isChecked()
        self.config["target_language"] = self.language_input.text().strip()
        self.config["ai_personality"] = self.personality_input.text().strip() or "Socranki"
        self.config["ui_font_size"] = self.font_size_spin.value()
        self.config["ui_box_height"] = self.box_height_spin.value()
        
        if self.config["model_name"].startswith("Error:") or self.config["model_name"] in ["Fetching models...", "No models found"]:
            self.config["model_name"] = ""
        self.config["custom_api_url"] = self.custom_url_input.text().strip()
        mw.addonManager.writeConfig(self.addon_name, self.config)
        self.accept()
