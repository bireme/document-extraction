# Resultados benchmark FASE18 — preprocesado OCR

PDFs: 56226_10006003233, 56335_10006001043, 56829_10006002445, 56884_10006000749, 56908_10006003232, 57134_10006001191 (máx 4 págs c/u, 300 dpi, lang por+eng+spa)

| técnica | págs | conf media | Δconf | palabras | Δpal % | segundos | Δt % |
|---|---|---|---|---|---|---|---|
| baseline | 13 | 93.15 | +0.00 | 2903 | +0.0% | 27.6 | +0.0% |
| gray | 13 | 93.97 | +0.82 | 3020 | +4.0% | 23.6 | -14.6% |
| autocontrast | 13 | 93.74 | +0.59 | 3061 | +5.4% | 23.9 | -13.4% |
| deskew | 13 | 94.14 | +0.99 | 2998 | +3.3% | 23.7 | -14.2% |
| combo | 13 | 93.44 | +0.30 | 3058 | +5.3% | 24.1 | -12.6% |
| lang_por | 13 | 92.73 | -0.42 | 2879 | -0.8% | 22.6 | -18.0% |

## Detalle por página

```json
[
 {
  "pdf": "56226_10006003233",
  "page": 1,
  "technique": "baseline",
  "conf": 80.2,
  "words": 43,
  "seconds": 1.09,
  "angle": 0.0
 },
 {
  "pdf": "56226_10006003233",
  "page": 1,
  "technique": "gray",
  "conf": 79.42,
  "words": 45,
  "seconds": 0.89,
  "angle": 0.0
 },
 {
  "pdf": "56226_10006003233",
  "page": 1,
  "technique": "autocontrast",
  "conf": 82.23,
  "words": 29,
  "seconds": 0.93,
  "angle": 0.0
 },
 {
  "pdf": "56226_10006003233",
  "page": 1,
  "technique": "deskew",
  "conf": 81.01,
  "words": 42,
  "seconds": 1.05,
  "angle": -0.5
 },
 {
  "pdf": "56226_10006003233",
  "page": 1,
  "technique": "combo",
  "conf": 82.88,
  "words": 42,
  "seconds": 1.07,
  "angle": -0.5
 },
 {
  "pdf": "56226_10006003233",
  "page": 1,
  "technique": "lang_por",
  "conf": 80.44,
  "words": 43,
  "seconds": 0.83,
  "angle": 0.0
 },
 {
  "pdf": "56226_10006003233",
  "page": 2,
  "technique": "baseline",
  "conf": 95.07,
  "words": 338,
  "seconds": 2.95,
  "angle": 0.0
 },
 {
  "pdf": "56226_10006003233",
  "page": 2,
  "technique": "gray",
  "conf": 95.87,
  "words": 334,
  "seconds": 2.12,
  "angle": 0.0
 },
 {
  "pdf": "56226_10006003233",
  "page": 2,
  "technique": "autocontrast",
  "conf": 95.93,
  "words": 334,
  "seconds": 2.26,
  "angle": 0.0
 },
 {
  "pdf": "56226_10006003233",
  "page": 2,
  "technique": "deskew",
  "conf": 95.38,
  "words": 337,
  "seconds": 2.15,
  "angle": -3.25
 },
 {
  "pdf": "56226_10006003233",
  "page": 2,
  "technique": "combo",
  "conf": 90.91,
  "words": 343,
  "seconds": 2.5,
  "angle": 3.25
 },
 {
  "pdf": "56226_10006003233",
  "page": 2,
  "technique": "lang_por",
  "conf": 95.06,
  "words": 338,
  "seconds": 2.64,
  "angle": 0.0
 },
 {
  "pdf": "56335_10006001043",
  "page": 1,
  "technique": "baseline",
  "conf": 92.81,
  "words": 116,
  "seconds": 1.87,
  "angle": 0.0
 },
 {
  "pdf": "56335_10006001043",
  "page": 1,
  "technique": "gray",
  "conf": 88.08,
  "words": 169,
  "seconds": 2.49,
  "angle": 0.0
 },
 {
  "pdf": "56335_10006001043",
  "page": 1,
  "technique": "autocontrast",
  "conf": 90.46,
  "words": 204,
  "seconds": 2.25,
  "angle": 0.0
 },
 {
  "pdf": "56335_10006001043",
  "page": 1,
  "technique": "deskew",
  "conf": 88.08,
  "words": 169,
  "seconds": 2.48,
  "angle": 0.0
 },
 {
  "pdf": "56335_10006001043",
  "page": 1,
  "technique": "combo",
  "conf": 90.46,
  "words": 204,
  "seconds": 2.35,
  "angle": 0.0
 },
 {
  "pdf": "56335_10006001043",
  "page": 1,
  "technique": "lang_por",
  "conf": 91.27,
  "words": 116,
  "seconds": 1.39,
  "angle": 0.0
 },
 {
  "pdf": "56335_10006001043",
  "page": 2,
  "technique": "baseline",
  "conf": 79.47,
  "words": 114,
  "seconds": 2.29,
  "angle": 0.0
 },
 {
  "pdf": "56335_10006001043",
  "page": 2,
  "technique": "gray",
  "conf": 92.8,
  "words": 84,
  "seconds": 1.14,
  "angle": 0.0
 },
 {
  "pdf": "56335_10006001043",
  "page": 2,
  "technique": "autocontrast",
  "conf": 83.56,
  "words": 100,
  "seconds": 1.49,
  "angle": 0.0
 },
 {
  "pdf": "56335_10006001043",
  "page": 2,
  "technique": "deskew",
  "conf": 92.8,
  "words": 84,
  "seconds": 1.19,
  "angle": 0.0
 },
 {
  "pdf": "56335_10006001043",
  "page": 2,
  "technique": "combo",
  "conf": 83.56,
  "words": 100,
  "seconds": 1.57,
  "angle": 0.0
 },
 {
  "pdf": "56335_10006001043",
  "page": 2,
  "technique": "lang_por",
  "conf": 75.6,
  "words": 93,
  "seconds": 1.65,
  "angle": 0.0
 },
 {
  "pdf": "56829_10006002445",
  "page": 1,
  "technique": "baseline",
  "conf": 96.29,
  "words": 5,
  "seconds": 0.42,
  "angle": 0.0
 },
 {
  "pdf": "56829_10006002445",
  "page": 1,
  "technique": "gray",
  "conf": 79.27,
  "words": 12,
  "seconds": 0.42,
  "angle": 0.0
 },
 {
  "pdf": "56829_10006002445",
  "page": 1,
  "technique": "autocontrast",
  "conf": 79.09,
  "words": 12,
  "seconds": 0.43,
  "angle": 0.0
 },
 {
  "pdf": "56829_10006002445",
  "page": 1,
  "technique": "deskew",
  "conf": 0.0,
  "words": 0,
  "seconds": 0.38,
  "angle": -3.25
 },
 {
  "pdf": "56829_10006002445",
  "page": 1,
  "technique": "combo",
  "conf": 0.0,
  "words": 0,
  "seconds": 0.37,
  "angle": -3.25
 },
 {
  "pdf": "56829_10006002445",
  "page": 1,
  "technique": "lang_por",
  "conf": 96.29,
  "words": 5,
  "seconds": 0.38,
  "angle": 0.0
 },
 {
  "pdf": "56829_10006002445",
  "page": 2,
  "technique": "baseline",
  "conf": 94.78,
  "words": 7,
  "seconds": 0.55,
  "angle": 0.0
 },
 {
  "pdf": "56829_10006002445",
  "page": 2,
  "technique": "gray",
  "conf": 67.78,
  "words": 13,
  "seconds": 0.5,
  "angle": 0.0
 },
 {
  "pdf": "56829_10006002445",
  "page": 2,
  "technique": "autocontrast",
  "conf": 66.87,
  "words": 13,
  "seconds": 0.5,
  "angle": 0.0
 },
 {
  "pdf": "56829_10006002445",
  "page": 2,
  "technique": "deskew",
  "conf": 96.29,
  "words": 3,
  "seconds": 0.44,
  "angle": -2.75
 },
 {
  "pdf": "56829_10006002445",
  "page": 2,
  "technique": "combo",
  "conf": 96.29,
  "words": 5,
  "seconds": 0.47,
  "angle": 3.25
 },
 {
  "pdf": "56829_10006002445",
  "page": 2,
  "technique": "lang_por",
  "conf": 89.73,
  "words": 7,
  "seconds": 0.45,
  "angle": 0.0
 },
 {
  "pdf": "56829_10006002445",
  "page": 3,
  "technique": "baseline",
  "conf": 95.2,
  "words": 486,
  "seconds": 3.29,
  "angle": 0.0
 },
 {
  "pdf": "56829_10006002445",
  "page": 3,
  "technique": "gray",
  "conf": 95.77,
  "words": 512,
  "seconds": 3.03,
  "angle": 0.0
 },
 {
  "pdf": "56829_10006002445",
  "page": 3,
  "technique": "autocontrast",
  "conf": 95.73,
  "words": 514,
  "seconds": 3.02,
  "angle": 0.0
 },
 {
  "pdf": "56829_10006002445",
  "page": 3,
  "technique": "deskew",
  "conf": 95.77,
  "words": 512,
  "seconds": 3.01,
  "angle": 0.0
 },
 {
  "pdf": "56829_10006002445",
  "page": 3,
  "technique": "combo",
  "conf": 95.73,
  "words": 514,
  "seconds": 3.05,
  "angle": 0.0
 },
 {
  "pdf": "56829_10006002445",
  "page": 3,
  "technique": "lang_por",
  "conf": 94.9,
  "words": 486,
  "seconds": 3.02,
  "angle": 0.0
 },
 {
  "pdf": "56884_10006000749",
  "page": 1,
  "technique": "baseline",
  "conf": 93.02,
  "words": 314,
  "seconds": 2.02,
  "angle": 0.0
 },
 {
  "pdf": "56884_10006000749",
  "page": 1,
  "technique": "gray",
  "conf": 94.02,
  "words": 300,
  "seconds": 1.62,
  "angle": 0.0
 },
 {
  "pdf": "56884_10006000749",
  "page": 1,
  "technique": "autocontrast",
  "conf": 94.0,
  "words": 301,
  "seconds": 1.64,
  "angle": 0.0
 },
 {
  "pdf": "56884_10006000749",
  "page": 1,
  "technique": "deskew",
  "conf": 94.02,
  "words": 300,
  "seconds": 1.64,
  "angle": 0.0
 },
 {
  "pdf": "56884_10006000749",
  "page": 1,
  "technique": "combo",
  "conf": 94.0,
  "words": 301,
  "seconds": 1.7,
  "angle": 0.0
 },
 {
  "pdf": "56884_10006000749",
  "page": 1,
  "technique": "lang_por",
  "conf": 92.16,
  "words": 313,
  "seconds": 1.71,
  "angle": 0.0
 },
 {
  "pdf": "56884_10006000749",
  "page": 2,
  "technique": "baseline",
  "conf": 94.55,
  "words": 504,
  "seconds": 3.27,
  "angle": 0.0
 },
 {
  "pdf": "56884_10006000749",
  "page": 2,
  "technique": "gray",
  "conf": 94.57,
  "words": 504,
  "seconds": 2.61,
  "angle": 0.0
 },
 {
  "pdf": "56884_10006000749",
  "page": 2,
  "technique": "autocontrast",
  "conf": 94.59,
  "words": 504,
  "seconds": 2.61,
  "angle": 0.0
 },
 {
  "pdf": "56884_10006000749",
  "page": 2,
  "technique": "deskew",
  "conf": 94.57,
  "words": 504,
  "seconds": 2.53,
  "angle": 0.0
 },
 {
  "pdf": "56884_10006000749",
  "page": 2,
  "technique": "combo",
  "conf": 94.59,
  "words": 504,
  "seconds": 2.58,
  "angle": 0.0
 },
 {
  "pdf": "56884_10006000749",
  "page": 2,
  "technique": "lang_por",
  "conf": 93.84,
  "words": 504,
  "seconds": 2.43,
  "angle": 0.0
 },
 {
  "pdf": "56908_10006003232",
  "page": 1,
  "technique": "baseline",
  "conf": 93.72,
  "words": 179,
  "seconds": 2.07,
  "angle": 0.0
 },
 {
  "pdf": "56908_10006003232",
  "page": 1,
  "technique": "gray",
  "conf": 93.72,
  "words": 183,
  "seconds": 1.85,
  "angle": 0.0
 },
 {
  "pdf": "56908_10006003232",
  "page": 1,
  "technique": "autocontrast",
  "conf": 93.93,
  "words": 182,
  "seconds": 1.89,
  "angle": 0.0
 },
 {
  "pdf": "56908_10006003232",
  "page": 1,
  "technique": "deskew",
  "conf": 93.72,
  "words": 183,
  "seconds": 1.88,
  "angle": 0.0
 },
 {
  "pdf": "56908_10006003232",
  "page": 1,
  "technique": "combo",
  "conf": 93.93,
  "words": 182,
  "seconds": 1.87,
  "angle": 0.0
 },
 {
  "pdf": "56908_10006003232",
  "page": 1,
  "technique": "lang_por",
  "conf": 93.57,
  "words": 179,
  "seconds": 1.6,
  "angle": 0.0
 },
 {
  "pdf": "56908_10006003232",
  "page": 2,
  "technique": "baseline",
  "conf": 80.85,
  "words": 125,
  "seconds": 2.42,
  "angle": 0.0
 },
 {
  "pdf": "56908_10006003232",
  "page": 2,
  "technique": "gray",
  "conf": 90.79,
  "words": 197,
  "seconds": 2.12,
  "angle": 0.0
 },
 {
  "pdf": "56908_10006003232",
  "page": 2,
  "technique": "autocontrast",
  "conf": 90.64,
  "words": 196,
  "seconds": 2.14,
  "angle": 0.0
 },
 {
  "pdf": "56908_10006003232",
  "page": 2,
  "technique": "deskew",
  "conf": 90.79,
  "words": 197,
  "seconds": 2.25,
  "angle": 0.0
 },
 {
  "pdf": "56908_10006003232",
  "page": 2,
  "technique": "combo",
  "conf": 90.64,
  "words": 196,
  "seconds": 2.13,
  "angle": 0.0
 },
 {
  "pdf": "56908_10006003232",
  "page": 2,
  "technique": "lang_por",
  "conf": 80.41,
  "words": 125,
  "seconds": 1.99,
  "angle": 0.0
 },
 {
  "pdf": "57134_10006001191",
  "page": 1,
  "technique": "baseline",
  "conf": 71.21,
  "words": 31,
  "seconds": 1.25,
  "angle": 0.0
 },
 {
  "pdf": "57134_10006001191",
  "page": 1,
  "technique": "gray",
  "conf": 80.93,
  "words": 26,
  "seconds": 0.81,
  "angle": 0.0
 },
 {
  "pdf": "57134_10006001191",
  "page": 1,
  "technique": "autocontrast",
  "conf": 70.86,
  "words": 31,
  "seconds": 0.83,
  "angle": 0.0
 },
 {
  "pdf": "57134_10006001191",
  "page": 1,
  "technique": "deskew",
  "conf": 82.19,
  "words": 26,
  "seconds": 0.89,
  "angle": 3.25
 },
 {
  "pdf": "57134_10006001191",
  "page": 1,
  "technique": "combo",
  "conf": 81.04,
  "words": 26,
  "seconds": 1.0,
  "angle": 3.25
 },
 {
  "pdf": "57134_10006001191",
  "page": 1,
  "technique": "lang_por",
  "conf": 71.86,
  "words": 29,
  "seconds": 0.87,
  "angle": 0.0
 },
 {
  "pdf": "57134_10006001191",
  "page": 2,
  "technique": "baseline",
  "conf": 96.15,
  "words": 641,
  "seconds": 4.12,
  "angle": 0.0
 },
 {
  "pdf": "57134_10006001191",
  "page": 2,
  "technique": "gray",
  "conf": 96.16,
  "words": 641,
  "seconds": 3.97,
  "angle": 0.0
 },
 {
  "pdf": "57134_10006001191",
  "page": 2,
  "technique": "autocontrast",
  "conf": 96.19,
  "words": 641,
  "seconds": 3.92,
  "angle": 0.0
 },
 {
  "pdf": "57134_10006001191",
  "page": 2,
  "technique": "deskew",
  "conf": 96.16,
  "words": 641,
  "seconds": 3.8,
  "angle": 0.0
 },
 {
  "pdf": "57134_10006001191",
  "page": 2,
  "technique": "combo",
  "conf": 96.19,
  "words": 641,
  "seconds": 3.46,
  "angle": 0.0
 },
 {
  "pdf": "57134_10006001191",
  "page": 2,
  "technique": "lang_por",
  "conf": 95.94,
  "words": 641,
  "seconds": 3.68,
  "angle": 0.0
 }
]
```
