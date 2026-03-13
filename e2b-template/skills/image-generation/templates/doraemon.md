# Doraemon 8-Panel Comic Generator

## Workflow

1. Extract story context (theme, gadget, conflict, punchline)
2. Map to 8 narrative beats
3. Use the provided prompt template to generate the JSON prompt file

## Panel Layout

```
┌─────────┬─────────┐
│ Panel 1 │ Panel 2 │  Row 1: y=200, height=380
├─────────┼─────────┤
│ Panel 3 │ Panel 4 │  Row 2: y=600, height=380
├─────────┼─────────┤
│ Panel 5 │ Panel 6 │  Row 3: y=1000, height=380
├─────────┼─────────┤
│ Panel 7 │ Panel 8 │  Row 4: y=1400, height=380
└─────────┴─────────┘
Left column: x=90, width=450
Right column: x=540, width=450
```

## Characters

* Doraemon
* Nobita
* Shizuka
* Giant
* Suneo

## Prompt Template

```json
{
  "canvas": {
    "width": 1080,
    "height": 1920,
    "background": { "type": "solid", "color": "#F0F8FF" }
  },
  "header": {
    "title": {
      "text": "[Story Title]",
      "position": { "x": 540, "y": 100 },
      "style": {
        "font_family": "Doraemon, sans-serif",
        "font_size": 56,
        "font_weight": "bold",
        "color": "#0095D9",
        "text_align": "center",
        "stroke": "#FFFFFF",
        "stroke_width": 4,
        "text_shadow": "3px 3px 0px #FFD700"
      }
    }
  },
  "panels": [
    {
      "id": "panel1",
      "position": { "x": 90, "y": 200 },
      "size": { "width": 450, "height": 380 },
      "border": { "width": 4, "color": "#000000", "radius": 12 },
      "background": "#FFFFFF",
      "scene": {
        "location": "[Location name]",
        "characters": [
          {
            "name": "[Character]",
            "position": { "x": 0, "y": 0 },
            "expression": "[Expression]",
            "pose": "[Pose description]"
          }
        ],
        "dialogues": [
          {
            "speaker": "[Character]",
            "text": "[Dialogue text]",
            "position": { "x": 0, "y": 0 },
            "style": {
              "bubble_type": "speech",
              "backgroundColor": "#FFFFFF",
              "border_color": "#000000",
              "font_size": 22,
              "text_align": "center"
            }
          }
        ],
        "props": []
      }
    }
  ],
  "footer": {
    "text": "[Closing note] - Doraemon",
    "position": { "x": 540, "y": 1860 },
    "style": {
      "font_family": "Doraemon, sans-serif",
      "font_size": 24,
      "color": "#0095D9",
      "text_align": "center"
    }
  },
}
```

## Story Pattern

Setup → Problem → Gadget → Misuse → Backfire → Chaos → Consequence → Ironic Punchline

## Aspect Ratio

9:16
