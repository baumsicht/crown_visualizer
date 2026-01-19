import os
import math
import re

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsProject,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
    QgsField,
    QgsCoordinateTransform,
    QgsUnitTypes,
    QgsWkbTypes,
)

from .treesta_crown_visualizer_dialog import TreestaCrownVisualizerDialog


class TreestaCrownVisualizer:
    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "treesta_crown_icon.png")
        self.action = QAction(QIcon(icon_path), "Treesta Crown Visualizer", self.iface.mainWindow())
        self.action.triggered.connect(self.run)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("Treesta Tools", self.action)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("Treesta Tools", self.action)

    # ---------------- UI helpers ----------------
    def _point_layers(self):
        layers = []
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsVectorLayer) and lyr.geometryType() == QgsWkbTypes.PointGeometry:
                layers.append(lyr)
        return layers

    def _autodetect_fields(self, layer: QgsVectorLayer):
        """
        Prefer crown_radius_1..4 (radius = center -> edge, meters).
        Fallback: crown_diameter_1..4 (diameter).
        Extra fallback: pattern match (radius|diameter) + _1.._4.
        Returns dict {0:field, 90:field, 180:field, 270:field} or {}.
        """
        names = [f.name() for f in layer.fields()]

        # 1) preferred: exact radius
        r = ["crown_radius_1", "crown_radius_2", "crown_radius_3", "crown_radius_4"]
        if all(n in names for n in r):
            return {0: r[0], 90: r[1], 180: r[2], 270: r[3]}

        # 2) exact diameter fallback
        d = ["crown_diameter_1", "crown_diameter_2", "crown_diameter_3", "crown_diameter_4"]
        if all(n in names for n in d):
            return {0: d[0], 90: d[1], 180: d[2], 270: d[3]}

        # 3) pattern fallback: anything containing 'radius' and ending _1.._4
        def find_by_pattern(keyword: str):
            found = {}
            for i, angle in [(1, 0), (2, 90), (3, 180), (4, 270)]:
                rx = re.compile(rf".*{keyword}.*_{i}$", re.IGNORECASE)
                match = next((n for n in names if rx.match(n)), None)
                if match:
                    found[angle] = match
            return found if len(found) == 4 else {}

        found_radius = find_by_pattern("radius")
        if found_radius:
            return found_radius

        found_diameter = find_by_pattern("diameter")
        if found_diameter:
            return found_diameter

        return {}

    def _populate_field_combos(self, dialog, layer: QgsVectorLayer):
        field_names = [f.name() for f in layer.fields()]
        for combo in [dialog.field_north, dialog.field_east, dialog.field_south, dialog.field_west]:
            combo.clear()
            combo.addItems(field_names)

        detected = self._autodetect_fields(layer)
        if detected:
            dialog.field_north.setCurrentText(detected[0])
            dialog.field_east.setCurrentText(detected[90])
            dialog.field_south.setCurrentText(detected[180])
            dialog.field_west.setCurrentText(detected[270])

    def _set_info(self, dialog, text: str, is_error: bool = False):
        """
        If text is empty -> hide label.
        Else show label as red (error) or orange (warning/info).
        """
        if not text:
            dialog.label_crs_warning.setVisible(False)
            return

        dialog.label_crs_warning.setVisible(True)
        dialog.label_crs_warning.setText(text)
        if is_error:
            dialog.label_crs_warning.setStyleSheet("color: red;")
        else:
            dialog.label_crs_warning.setStyleSheet("color: #a15c00;")  # orange-ish

    def run(self):
        dialog = TreestaCrownVisualizerDialog()
        dialog.label_crs_warning.setVisible(False)

        layers = self._point_layers()
        if not layers:
            self.iface.messageBar().pushWarning("Treesta", "No point layers found in the project.")
            return

        dialog.layer_combo.clear()
        dialog.layer_combo.addItems([layer.name() for layer in layers])
        layer_map = {layer.name(): layer for layer in layers}

        # default layer
        if "Trees" in layer_map:
            dialog.layer_combo.setCurrentText("Trees")

        # initial population of fields
        self._populate_field_combos(dialog, layer_map[dialog.layer_combo.currentText()])

        # update fields when layer changes
        def on_layer_changed():
            lyr = layer_map.get(dialog.layer_combo.currentText())
            if lyr:
                self._populate_field_combos(dialog, lyr)

        dialog.layer_combo.currentIndexChanged.connect(on_layer_changed)

        # ------- validate BEFORE accept (button_box in your UI) -------
        button_box = getattr(dialog, "button_box", None)
        if not button_box:
            self.iface.messageBar().pushCritical("Treesta", "UI error: 'button_box' not found in dialog.")
            return

        ok_button = button_box.button(button_box.Ok)
        if not ok_button:
            self.iface.messageBar().pushCritical("Treesta", "UI error: OK button not found in 'button_box'.")
            return

        def validate_and_accept():
            selected_layer = layer_map.get(dialog.layer_combo.currentText())
            if not selected_layer:
                self._set_info(dialog, "No valid layer selected.", is_error=True)
                return

            target_crs = dialog.crs_selector.crs()
            if (target_crs is None) or (not target_crs.isValid()):
                self._set_info(dialog, "Please select a valid projected CRS with meter units.", is_error=True)
                return

            if target_crs.mapUnits() != QgsUnitTypes.DistanceMeters:
                self._set_info(
                    dialog,
                    f"CRS must be metric (meters). Selected: {target_crs.authid()}",
                    is_error=True,
                )
                return

            combos = [dialog.field_north, dialog.field_east, dialog.field_south, dialog.field_west]
            if any(not c.currentText() for c in combos):
                self._set_info(dialog, "Please select 4 fields for North/East/South/West.", is_error=True)
                return

            # Warn (non-blocking) if diameter fields selected
            selected_fields = [c.currentText().lower() for c in combos]
            if any("diameter" in n for n in selected_fields):
                self._set_info(
                    dialog,
                    "Diameter fields selected. Tool will convert diameter → radius (divide by 2).",
                    is_error=False,
                )
            else:
                self._set_info(dialog, "")

            dialog.accept()

        # connect validation (avoid duplicate connections)
        try:
            ok_button.clicked.disconnect()
        except Exception:
            pass
        ok_button.clicked.connect(validate_and_accept)

        if not dialog.exec_():
            return

        # gather settings after accept
        selected_layer = layer_map.get(dialog.layer_combo.currentText())
        target_crs = dialog.crs_selector.crs()

        selected_only = False
        if hasattr(dialog, "selected_only_checkbox") and dialog.selected_only_checkbox is not None:
            selected_only = dialog.selected_only_checkbox.isChecked()

        field_map = {
            0: dialog.field_north.currentText(),
            90: dialog.field_east.currentText(),
            180: dialog.field_south.currentText(),
            270: dialog.field_west.currentText(),
        }

        # MessageBar info that actually stays visible
        selected_fields_lower = [field_map[k].lower() for k in [0, 90, 180, 270]]
        if any("diameter" in n for n in selected_fields_lower):
            self.iface.messageBar().pushWarning(
                "Treesta", "Diameter fields selected. Converting diameter → radius (divide by 2)."
            )

        self.create_crown_layer(selected_layer, field_map, target_crs, selected_only)

    # ---------------- style ----------------
    def apply_default_style(self, layer: QgsVectorLayer):
        from qgis.core import QgsFillSymbol

        symbol = QgsFillSymbol.createSimple({
            "color": "60,160,60,80",        # RGBA: half transparent green
            "outline_color": "40,120,40,200",
            "outline_width": "0.4",
            "outline_style": "solid",
        })
        layer.renderer().setSymbol(symbol)
        layer.triggerRepaint()

    # ---------------- geometry logic ----------------
    def interpolierter_radius(self, radii, winkel):
        winkel = winkel % 360
        richtungen = [0, 90, 180, 270]
        for i in range(len(richtungen)):
            w1 = richtungen[i]
            w2 = richtungen[(i + 1) % len(richtungen)]
            if w1 <= winkel < w2 or (w1 > w2 and (winkel >= w1 or winkel < w2)):
                r1 = radii[w1]
                r2 = radii[w2]
                delta = (w2 - w1) % 360
                faktor = (winkel - w1) / delta if delta != 0 else 0
                t = (1 - math.cos(faktor * math.pi)) / 2
                return (1 - t) * r1 + t * r2
        return radii[0]

    def create_crown_layer(self, layer, field_map, target_crs, selected_only=False):
        crown_layer = QgsVectorLayer("Polygon?crs=" + target_crs.authid(), "Crown", "memory")
        provider = crown_layer.dataProvider()
        provider.addAttributes([QgsField(name="id", type=QVariant.Int, typeName="Integer")])
        crown_layer.updateFields()

        transform = QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance())

        if selected_only:
            features = layer.selectedFeatures()
        else:
            features = list(layer.getFeatures())

        if not features:
            self.iface.messageBar().pushWarning("Treesta", "No features found (empty layer or nothing selected).")
            return

        # Diameter fields? -> convert to radius
        field_names_lower = [field_map[k].lower() for k in [0, 90, 180, 270]]
        convert_diameter_to_radius = any("diameter" in n for n in field_names_lower)

        added = 0
        for feature in features:
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue

            try:
                center = transform.transform(geom.asPoint())
            except Exception:
                continue

            try:
                radii = {}
                for k in [0, 90, 180, 270]:
                    v = feature[field_map[k]]
                    if v is None:
                        raise ValueError("NULL")
                    v = float(v)
                    if v <= 0:
                        raise ValueError("<=0")
                    radii[k] = (v / 2.0) if convert_diameter_to_radius else v
            except Exception:
                continue

            polygon_pts = []
            for angle in range(0, 360, 5):
                r = self.interpolierter_radius(radii, angle)
                rad = math.radians(angle)
                x = center.x() + r * math.sin(rad)
                y = center.y() + r * math.cos(rad)
                polygon_pts.append(QgsPointXY(x, y))
            polygon_pts.append(polygon_pts[0])

            poly = QgsFeature()
            poly.setGeometry(QgsGeometry.fromPolygonXY([polygon_pts]))
            poly.setAttributes([feature.id()])
            provider.addFeature(poly)
            added += 1

        crown_layer.updateExtents()

        # Apply simple default style (no QML dependency)
        self.apply_default_style(crown_layer)

        QgsProject.instance().addMapLayer(crown_layer)

        suffix = " (diameter→radius applied)" if convert_diameter_to_radius else ""
        self.iface.messageBar().pushSuccess("Treesta", f"Crown layer created: {added} polygons.{suffix}")
