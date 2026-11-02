# Présentation — JARVIS (Ydays)

| Fichier | Pour quoi |
|---|---|
| `Jarvis-slides.pptx` | Le deck (13 slides), texte modifiable, notes de l'orateur sous chaque slide |
| `Jarvis-slides.pdf` | Le même deck en PDF, à rendre ou à projeter sans PowerPoint |
| `Jarvis-slides.html` | Version web autonome : ouvrir dans un navigateur, flèches pour avancer, `F` pour le plein écran |
| `Jarvis-motion.mp4` | La vidéo motion design (49 s, 1920×1080, 30 i/s) avec voix off et musique de fond |
| `source/` | Les sources (`slides.html`, `motion.html`, `narration.json`, `audio.py`) et le script qui régénère tout |

Les polices sont Space Grotesk, Inter et Noto Sans Mono (Google Fonts, gratuites). Installez-les sur le PC de projection si vous utilisez le `.pptx`, sinon PowerPoint les remplace.

## Modifier puis régénérer

Changez `source/slides.html` ou `source/motion.html`, puis depuis la racine du projet :

```bash
.venv/bin/python présentation/source/build.py            # tout
.venv/bin/python présentation/source/build.py slides     # PPTX + PDF + web
.venv/bin/python présentation/source/build.py motion     # MP4 (2 à 5 min)
.venv/bin/python présentation/source/build.py son        # seulement le son, sans refaire l'image
```

## Le son de la vidéo

- **Voix off** : le texte et le moment de chaque phrase sont dans `source/narration.json` (`at` = début en secondes, `until` = limite à ne pas dépasser). La voix est celle de Jarvis (Charon), synthétisée par Gemini TTS avec la clé de `config/api_keys.json`. Chaque phrase est mise en cache dans `source/cache/` : seule une phrase modifiée est resynthétisée. Une phrase trop longue pour son créneau est accélérée (×1,15 au maximum) ; au-delà, le build le signale et il faut la raccourcir.
- **Musique** : composée par `source/audio.py` (numpy, sans échantillon ni licence). Les accords changent avec les scènes, avec des souffles sur les transitions et un impact sur chaque « JARVIS ». Elle reste environ 14 dB sous la voix et s'abaisse encore quand la voix parle.
- `source/cache/` contient les pistes séparées (`voix.wav`, `musique.wav`) et le rendu muet (`motion-muet.mp4`).

Le script passe par les moteurs de rendu de Jarvis lui-même : `core/html_deck.py` pour le PowerPoint et `actions/create_motion_video.py` pour la vidéo, rendue image par image sur une horloge virtuelle. `source/motion.html` se lit aussi directement dans un navigateur ; un clic relance l'animation.
