import os
import math
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsProject, QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer,
    QgsField, QgsCoordinateReferenceSystem, QgsProcessingFeedback
)
from .treesta_crown_visualizer_dialog import TreestaCrownVisualizerDialog
import processing

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
        dialog = TreestaCrownVisualizerDialog()

        # Punktlayer sammeln
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
            dialog.field_north.setCurrentText("crown_radius_1")
            dialog.field_east.setCurrentText("crown_radius_2")
            dialog.field_south.setCurrentText("crown_radius_3")
            dialog.field_west.setCurrentText("crown_radius_4")

        if dialog.exec_():
            source_layer = layer_map.get(dialog.layer_combo.currentText())
            if not source_layer:
                self.iface.messageBar().pushWarning("Treesta", "No valid layer selected.")
                return

            # Ziel-KBS fix setzen (metrisch)
            target_crs = QgsCoordinateReferenceSystem("EPSG:25832")

            # Reprojektion durchführen
            result = processing.run(
                "native:reprojectlayer",
                {
                    'INPUT': source_layer,
                    'TARGET_CRS': target_crs,
                    'OUTPUT': 'memory:'
                },
                feedback=QgsProcessingFeedback()
            )
            layer = result['OUTPUT']

            fields = {
                0: dialog.field_north.currentText(),
                90: dialog.field_east.currentText(),
                180: dialog.field_south.currentText(),
                270: dialog.field_west.currentText()
            }

            self.create_crown_layer(layer, fields)

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

    def create_crown_layer(self, layer, field_map):
        crown_layer = QgsVectorLayer("Polygon?crs=EPSG:25832", "Crown", "memory")
        provider = crown_layer.dataProvider()
        provider.addAttributes([QgsField("id", QVariant.Int)])
        crown_layer.updateFields()

        features = layer.selectedFeatures()
        if not features:
            features = layer.getFeatures()

        for feature in features:
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue

            try:
                radii = {k: float(feature[field_map[k]]) for k in field_map}
            except Exception:
                continue

            center = geom.asPoint()  # bereits in EPSG:25832
            polygon_pts = []

            for angle in range(0, 360, 5):
                r = self.interpolierter_radius(radii, angle)
                rad = math.radians(angle)
                x = center.x() + r * math.sin(rad)
                y = center.y() + r * math.cos(rad)
                polygon_pts.append(QgsPointXY(x, y))

            polygon_pts.append(polygon_pts[0])  # schließen

            poly = QgsFeature()
            poly.setGeometry(QgsGeometry.fromPolygonXY([polygon_pts]))
            poly.setAttributes([feature.id()])
            provider.addFeature(poly)

        crown_layer.updateExtents()
        QgsProject.instance().addMapLayer(crown_layer)
