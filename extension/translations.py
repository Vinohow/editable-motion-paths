# SPDX-License-Identifier: GPL-3.0-or-later
"""Interface translations.

The interface is written in English. Blender picks a translation from this
table when its own language is set to one listed here. To add a language,
add a ``"xx_XX": {English: Translation}`` block to ``_MESSAGES``.
"""

_MESSAGES = {
    "fr_FR": {
        # Panel
        "Editable Motion Paths": "Trajectoires éditables",
        "Motion Path": "Trajectoire",
        "Select an object or a bone": "Sélectionne un objet ou un os",
        "Path may be outdated: click Refresh": "Trajectoire peut-être périmée : clique sur Recalculer",
        "Frame {}: {}": "Frame {} : {}",
        "Corner": "Angle",
        "Smooth": "Courbe",
        "Auto": "Auto",
        "Mixed": "Mixte",
        "Key": "Clé",
        "Display": "Affichage",
        "Frame Range": "Plage de frames",
        "Appearance": "Apparence",
        "Editing": "Édition",
        "Performance": "Performance",
        "Shortcuts": "Raccourcis",
        "Parent motion could not be evaluated": "Le mouvement du parent n'a pas pu être évalué",
        "Last refresh: {} frames in {} ms": "Dernier calcul : {} frames en {} ms",
        # Shortcuts
        "Click": "Clic",
        "Drag": "Glisser",
        "Shift + Click": "Maj + Clic",
        "Alt + Click": "Alt + Clic",
        "Alt + Drag": "Alt + Glisser",
        "Select a key": "Sélectionner une clé",
        "Move a key or a handle": "Déplacer une clé ou une poignée",
        "Add to the selection": "Ajouter à la sélection",
        "Shape the tangent": "Régler la tangente",
        "Lock to an axis": "Verrouiller sur un axe",
        "Lock to a plane": "Verrouiller sur un plan",
        "Snap while dragging": "Aimanter pendant le glisser",
        # Operators
        "Refresh Motion Paths": "Recalculer les trajectoires",
        "Recalculate the displayed motion paths, including the motion of parents and constraints":
            "Recalcule les trajectoires affichées, en tenant compte du mouvement des parents et des contraintes",
        "Select an animated object or bone":
            "Sélectionne un objet ou un os animé",
        "Could not evaluate the parent motion: the path may be approximate":
            "Impossible d'évaluer le mouvement du parent : la trajectoire peut être approximative",
        "Add Key at Current Frame": "Ajouter une clé à la frame courante",
        "Delete Selected Keys": "Supprimer les clés sélectionnées",
        "Delete the Location keyframes selected on the motion path":
            "Supprime les clés de position sélectionnées sur la trajectoire",
        "Set Handle Type": "Définir le type de poignée",
        "Change how the path bends through the selected key":
            "Change la façon dont la trajectoire passe par la clé sélectionnée",
        "Handle Type": "Type de poignée",
        "Smooth curve calculated by Blender": "Courbe lisse calculée par Blender",
        "Manual tangents kept aligned for a smooth transition":
            "Tangentes manuelles gardées alignées pour une transition lisse",
        "Each tangent is independent": "Chaque tangente est indépendante",
        "Straight segments and a sharp corner": "Segments droits et angle net",
        "Corner / Smooth": "Angle / Courbe",
        "Switch the selected key between a sharp corner and a smooth curve":
            "Bascule la clé sélectionnée entre un angle net et une courbe lisse",
        "Manual tangent  |  Release to confirm  |  Esc to cancel":
            "Tangente manuelle  |  Relâcher pour valider  |  Échap pour annuler",
        "Reset to Defaults": "Réinitialiser",
        "Reset every Editable Motion Paths preference (colors, sizes, behavior) to its default value":
            "Remet toutes les préférences d'Editable Motion Paths (couleurs, tailles, comportement) "
            "à leur valeur par défaut",
        # Drag header
        "Plane {}": "Plan {}",
        "Axis {}": "Axe {}",
        "Handle": "Poignée",
        "X/Y/Z: axis  |  Shift + X/Y/Z: plane  |  Same key again: free  |  Ctrl: snap":
            "X/Y/Z : axe  |  Maj + X/Y/Z : plan  |  Même touche : libre  |  Ctrl : aimanter",
        # Scene settings
        "Show Path": "Afficher la trajectoire",
        "Display the motion path in the 3D View": "Affiche la trajectoire dans la vue 3D",
        "Editable": "Éditable",
        "Edit the keys and handles of the path directly in the 3D View":
            "Modifie les clés et les poignées de la trajectoire directement dans la vue 3D",
        "Paths": "Trajectoires",
        "Which motion paths are displayed": "Quelles trajectoires sont affichées",
        "Only the active object or bone": "Seulement l'objet ou l'os actif",
        "Every selected object or bone": "Tous les objets ou os sélectionnés",
        "Frame range covered by the path": "Plage de frames couverte par la trajectoire",
        "From the first to the last Location keyframe": "De la première à la dernière clé de position",
        "Around Frame": "Autour de la frame",
        "A window of frames around the current frame": "Une fenêtre de frames autour de la frame courante",
        "The scene frame range": "La plage de frames de la scène",
        "Frames displayed before the current frame": "Frames affichées avant la frame courante",
        "Frames displayed after the current frame": "Frames affichées après la frame courante",
        # Preferences: display
        "Bezier Handles": "Poignées Bézier",
        "Show the handles of the selected key": "Affiche les poignées de la clé sélectionnée",
        "Direction Arrows": "Flèches de direction",
        "Show arrows along the path in the direction of the animation":
            "Affiche des flèches le long de la trajectoire, dans le sens de l'animation",
        "Past / Future Colors": "Couleurs passé / futur",
        "Use a different color before and after the current frame":
            "Utilise une couleur différente avant et après la frame courante",
        "Frame Numbers": "Numéros de frame",
        "Show the frame number next to each key": "Affiche le numéro de frame à côté de chaque clé",
        "Key Type Letters": "Lettres de type de clé",
        "Show a letter next to each key: V = Vector, S = Aligned, A = Automatic, F = Free":
            "Affiche une lettre à côté de chaque clé : V = Vector, S = Alignée, A = Automatique, F = Libre",
        "Frame Dots": "Points par frame",
        "Show a dot on every frame to read the spacing of the motion":
            "Affiche un point sur chaque frame pour lire l'espacement du mouvement",
        "Show the path through the geometry": "Affiche la trajectoire à travers la géométrie",
        # Preferences: appearance
        "Past Path": "Trajectoire passée",
        "Smooth Key": "Clé lissée",
        "Corner Key": "Clé en angle",
        "Selected Key": "Clé sélectionnée",
        "Handles": "Poignées",
        "Handle Lines": "Lignes des poignées",
        "Labels": "Étiquettes",
        "Line Width": "Épaisseur du trait",
        "Key Size": "Taille des clés",
        "Handle Size": "Taille des poignées",
        "Dot Size": "Taille des points",
        "Label Size": "Taille des étiquettes",
        "Key Outline": "Contour des clés",
        "Dark outline around keys, easier to read on busy backgrounds":
            "Contour sombre autour des clés, plus lisible sur un fond chargé",
        "Outline Width": "Épaisseur du contour",
        "Arrow Spacing": "Espacement des flèches",
        "Number of path samples between two arrows": "Nombre de points de trajectoire entre deux flèches",
        "Arrow Size": "Taille des flèches",
        # Preferences: editing
        "Click Tolerance": "Tolérance du clic",
        "Distance in pixels within which a key can be clicked":
            "Distance en pixels dans laquelle une clé peut être cliquée",
        "Snap Increment": "Pas d'aimantation",
        "Step used when dragging a key with Ctrl held": "Pas utilisé quand on déplace une clé en tenant Ctrl",
        "Constraint Space": "Espace des contraintes",
        "Axes used by the X/Y/Z constraints while dragging":
            "Axes utilisés par les contraintes X/Y/Z pendant le déplacement",
        "World X/Y/Z axes": "Axes X/Y/Z du monde",
        "Local axes of the animated object or bone": "Axes locaux de l'objet ou de l'os animé",
        "Axis Guide": "Guide d'axe",
        "Show the constraint axis while dragging": "Affiche l'axe de contrainte pendant le déplacement",
        "Key the current position of the active object or bone on the current frame":
            "Enregistre la position actuelle de l'objet ou de l'os actif sur la frame courante",
        "Show the path in Object or Pose Mode first": "Affiche d'abord la trajectoire en mode Objet ou Pose",
        "Edit Mode: view only": "Mode Édition : affichage seul",
        "Leave Edit Mode once to show the others": "Quitte une fois le mode Édition pour voir les autres",
        "Not animated": "Pas animé",
        "Curves: use control points": "Courbes : utilise les points de contrôle",
        "Control Points On / Off": "Points de contrôle activés / désactivés",
        "Switch dense keys (motion capture) between control points and real keys. "
        "Shortcut: Shift + Alt + C in the 3D View":
            "Bascule les clés denses (motion capture) entre points de contrôle et vraies clés. "
            "Raccourci : Maj + Alt + C dans la vue 3D",
        "Control points: on": "Points de contrôle : activés",
        "Control points: off (real keys)": "Points de contrôle : désactivés (vraies clés)",
        "Use Real Keys": "Utiliser les vraies clés",
        "Use Control Points": "Utiliser les points de contrôle",
        "Dense keys: real keys": "Clés denses : vraies clés",
        "Smooth Path": "Lisser la trajectoire",
        "Replace the path around the selected control points by a clean curve "
        "through the control points (Alt + click on a control point does the same)":
            "Remplace la trajectoire autour des points de contrôle sélectionnés par une courbe propre "
            "qui passe par eux (Alt + clic sur un point de contrôle fait la même chose)",
        "Frame {}": "Frame {}",
        "Dense keys: {} control points": "Clés denses : {} points de contrôle",
        "Drag a control point or any key": "Glisse un point de contrôle ou n'importe quelle clé",
        "Control Points": "Points de contrôle",
        "When there is a key on (almost) every frame, like motion capture, edit the path with a few "
        "control points: the keys around a dragged control point follow smoothly":
            "Quand il y a une clé sur (presque) chaque frame, comme en motion capture, édite la trajectoire avec "
            "quelques points de contrôle : les clés autour d'un point déplacé suivent en douceur",
        "Control Point Spacing": "Espacement des points de contrôle",
        "Frames between two control points": "Frames entre deux points de contrôle",
        "Dense Keys Opacity": "Opacité des clés denses",
        "Opacity of the keys that are not control points": "Opacité des clés qui ne sont pas des points de contrôle",
        "Animated by its bones": "Animé par ses os",
        "Select bones in Pose Mode": "Sélectionne des os en mode Pose",
        "Editable: drag keys, click path": "Éditable : glisse les clés, clique la trajectoire",
        "View only: moved by parents": "Affichage seul : bougé par ses parents",
        "Click the path to add a key": "Clique sur la trajectoire pour ajouter une clé",
        "{} paths shown": "{} trajectoires affichées",
        "Bone Point": "Point de l'os",
        "Point of the bone that draws the path": "Point de l'os qui trace la trajectoire",
        "Head": "Tête",
        "Path of the base of the bone": "Trajectoire de la base de l'os",
        "Tail": "Queue",
        "Path of the tip of the bone: best for hands and feet":
            "Trajectoire du bout de l'os : idéal pour les mains et les pieds",
        "New Key Preview": "Aperçu de nouvelle clé",
        "Click to Add Keys": "Cliquer pour ajouter des clés",
        "Hovering a path shows where a key would go; a click adds it without changing the motion":
            "Le survol d'une trajectoire montre où irait une clé ; un clic l'ajoute sans changer le mouvement",
        "Hover Distance": "Distance de survol",
        "Distance in pixels from the path within which the new key preview appears":
            "Distance en pixels à la trajectoire sous laquelle l'aperçu de nouvelle clé apparaît",
        # Preferences: performance
        "Auto Refresh": "Recalcul automatique",
        "Recalculate the path automatically when a parent or constraint changes. "
        "Turn off on very heavy rigs and use the Refresh button instead":
            "Recalcule la trajectoire automatiquement quand un parent ou une contrainte change. "
            "À désactiver sur les rigs très lourds, au profit du bouton Recalculer",
        "Adaptive Sampling": "Échantillonnage adaptatif",
        "Skip frames on long ranges to keep the viewport fast":
            "Saute des frames sur les longues plages pour garder une vue fluide",
        "Max Samples": "Échantillons max",
        "Maximum number of points evaluated along a path": "Nombre maximum de points évalués le long d'une trajectoire",
        "Frame Step": "Pas de frames",
        "Evaluate the path every N frames": "Évalue la trajectoire toutes les N frames",
    },
}

# Blender looks labels up in the default context and operator names in the
# "Operator" context: register every message in both.
TRANSLATIONS = {
    language: {
        (context, english): translated
        for english, translated in messages.items()
        for context in ("*", "Operator")
    }
    for language, messages in _MESSAGES.items()
}
