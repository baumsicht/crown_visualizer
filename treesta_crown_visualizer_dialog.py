from PyQt5 import uic
from PyQt5.QtWidgets import QDialog
import os

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'treesta_crown_visualizer_dialog_base.ui'))

class TreestaCrownVisualizerDialog(QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # Verbinde die ButtonBox-Signale mit accept/reject
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
