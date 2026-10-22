# Présentation — JARVIS (Ydays)

| Fichier | Pour quoi |
|---|---|
| `Jarvis-slides.pptx` | Le deck (13 slides), texte modifiable, notes de l'orateur sous chaque slide |
| `Jarvis-slides.pdf` | Le même deck en PDF, à rendre ou à projeter sans PowerPoint |
| `Jarvis-slides.html` | Version web autonome : ouvrir dans un navigateur, flèches pour avancer, `F` pour le plein écran |
| `Jarvis-motion.mp4` | La vidéo motion design (49 s, 1920×1080, 30 i/s, muette) |
| `source/` | Les sources (`slides.html`, `motion.html`) et le script qui régénère tout |

Les polices sont Space Grotesk, Inter et Noto Sans Mono (Google Fonts, gratuites). Installez-les sur le PC de projection si vous utilisez le `.pptx`, sinon PowerPoint les remplace.

## Modifier puis régénérer

Changez `source/slides.html` ou `source/motion.html`, puis depuis la racine du projet :

```bash
.venv/bin/python présentation/source/build.py            # tout
.venv/bin/python présentation/source/build.py slides     # PPTX + PDF + web
.venv/bin/python présentation/source/build.py motion     # MP4 (2 à 5 min)
```

Le script passe par les moteurs de rendu de Jarvis lui-même : `core/html_deck.py` pour le PowerPoint et `actions/create_motion_video.py` pour la vidéo, rendue image par image sur une horloge virtuelle. `source/motion.html` se lit aussi directement dans un navigateur ; un clic relance l'animation.
