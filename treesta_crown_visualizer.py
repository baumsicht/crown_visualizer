import os
import math
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsProject, QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer,
    QgsField, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsUnitTypes
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

    def run(self):
        from qgis.core import QgsVectorLayer

        dialog = TreestaCrownVisualizerDialog()

        # Lade Punkt-Vektorlayer
        layers = [
            l for l in QgsProject.instance().mapLayers().values()
            if isinstance(l, QgsVectorLayer) and l.geometryType() == 0
        ]
        dialog.layer_combo.clear()
        dialog.layer_combo.addItems([layer.name() for layer in layers])

        layer_map = {layer.name(): layer for layer in layers}
        if "Trees" in layer_map:
            dialog.layer_combo.setCurrentText("Trees")
            fields = layer_map["Trees"].fields()
            for fcombo in [dialog.field_north, dialog.field_east, dialog.field_south, dialog.field_west]:
                fcombo.clear()
                fcombo.addItems([f.name() for f in fields])
            dialog.field_north.setCurrentText("crown_diameter_1")
            dialog.field_east.setCurrentText("crown_diameter_2")
            dialog.field_south.setCurrentText("crown_diameter_3")
            dialog.field_west.setCurrentText("crown_diameter_4")

        if dialog.exec_():
            selected_layer = layer_map.get(dialog.layer_combo.currentText())
            if not selected_layer:
                self.iface.messageBar().pushWarning("Treesta", "No valid layer selected.")
                return

            fields = {
                0: dialog.field_north.currentText(),
                90: dialog.field_east.currentText(),
                180: dialog.field_south.currentText(),
                270: dialog.field_west.currentText()
            }

            target_crs = dialog.crs_selector.crs()

            # ✅ Einheit prüfen (Meter) und Warnung anzeigen
            if target_crs.mapUnits() != QgsUnitTypes.DistanceMeters:
                warning = f"Selected CRS ({target_crs.authid()}) is not metric. Please choose one with meter units."
                dialog.label_crs_warning.setText(warning)
                dialog.label_crs_warning.setStyleSheet("color: red")
                dialog.label_crs_warning.setVisible(True)
                return  # Dialog bleibt geöffnet
            else:
                dialog.label_crs_warning.setVisible(False)

            self.create_crown_layer(selected_layer, fields, target_crs)

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

    def create_crown_layer(self, layer, field_map, target_crs):
        crown_layer = QgsVectorLayer("Polygon?crs=" + target_crs.authid(), "Crown", "memory")
        provider = crown_layer.dataProvider()
        provider.addAttributes([QgsField("id", QVariant.Int)])
        crown_layer.updateFields()

        source_crs = layer.crs()
        transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())

        features = layer.selectedFeatures()
        if not features:
            features = layer.getFeatures()

        for feature in features:
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue
            try:
                center = transform.transform(geom.asPoint())
            except Exception:
                continue

            try:
                radii = {
                    k: feature[field_map[k]] / 2 for k in [0, 90, 180, 270]
                }
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

        crown_layer.updateExtents()
        QgsProject.instance().addMapLayer(crown_layer)
