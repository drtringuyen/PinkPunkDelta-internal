# PinkPunkDelta-internal

Blender 5.3 add-on for the Pink Punk Delta production: setup, texture baking and a Procreate live link. N-panel tab **PPD**.

## Names

The .blend's file name is the **Central**. Everything follows from it and from the object's name (F2):

| | Example |
|---|---|
| File | `VHC_Tractor.blend` |
| Object | `VHC_Tractor.Wheel` (type just `Wheel`) |
| Material | `MAT_VHC_Tractor.Wheel` |
| Textures | `textures/ALB_`, `NOR_`, `SHD_`, `TEX_VHC_Tractor.Wheel.png`, always 8192 x 8192 |
| Procreate | `textures/VHC_Tractor.Wheel.psd` |

- A rename takes the material, images and files along.
- Saving under another file name renames everything. Textures are copied while the old .blend exists, moved when it is gone.
- **Check All Links** checks and corrects it all, and scales textures that are not 8K.
- A replaced file keeps one previous copy in `textures/_previous`.
- Shift+D makes a new object with its own material and no textures; Alt+D stays an instance.

## 01.Setup
170 cm figure, list of set-up objects, **Setup Current**, **Create Setup Object** (RetopoFlow), **Check All Links**.
Setup adds `GN_SharpTubes` and a `MAT_` material with the nodes `PPD_ALB`, `PPD_NOR`, `PPD_SHD`, `PPD_TEX`. ALB and NOR go into `NPR`; SHD and TEX are left unconnected. The layout is yours to change: the add-on only swaps the images on those four nodes.

## 02.Bake & Link Texture
Per object: the Original, the Cage, and Bake ALB + NOR (Cycles, Selected to Active, on `uv_normal` or else the active UV map).

## 03.LiveLink
The four textures of each object (show, load, folder, reload) and its Procreate file.
1. **Prepare PSD**: UV layout at 25 %, TEX, SHD, ALB, NOR.
2. **Start LiveLink**, scan the QR code, get the PSD on the iPad and open it in Procreate.
3. Paint on SHD and TEX. Share > PSD > *Send to Blender* (the page explains the Shortcut, built once).

The address contains a key: do not share the QR code.

The page, the QR code and the shared folder all use the PC's name (for example `AUCO.local`), so a new IP number changes nothing. If the iPad does not find the name, type the number into **Address**.

## 04.Split Parts & Ramps
Edit Mode: select faces, **Add Split Part**. Each part has a color ramp whose steps are its light bands; faces in no part keep the plain NPR shading.
- Parts are one number per face (`PPD_PART`), so a face is in one part only.
- The ramps sit in the object's own copy of NPR, `NPR_<full name>`. After changing the shared `NPR`, press the refresh button beside Add Split Part: the ramps stay.
- **Ignore ALB**: the ramp alone colors the part.

## Install
`python install.py` copies the add-on into Blender 5.3 and reloads it; `python zip_addon.py` makes a zip.

## Tests
`blender -b --factory-startup -P tests/test_headless.py` and `tests/test_parts.py`

License: GPL-3.0-or-later. 03.LiveLink is based on Procreate Live Link 1.0.0 (GPL-3.0-or-later).
