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
| Shader | `NPR_VHC_Tractor.Wheel` (built from the object's parts and colors) |
| Procreate | `PPD_Procreate/To iPad/VHC_Tractor.Wheel_k3f9a2c.psd` (`k3f9a2c`: the object's key) |

- A rename takes the material, images and files along.
- Saving under another file name renames everything. Textures are copied while the old .blend exists, moved when it is gone.
- **Check All Links** checks and corrects it all, and scales textures that are not 8K.
- A replaced file keeps one previous copy in `textures/_previous`.
- Shift+D makes a new object with its own material and no textures; Alt+D stays an instance.

## 01.Setup
170 cm figure, list of set-up objects, **Setup Current**, **Create Setup Object** (RetopoFlow), **Check All Links**.
Setup adds `GN_SharpTubes` and a `MAT_` material with the nodes `PPD_ALB`, `PPD_NOR`, `PPD_SHD`, `PPD_TEX` and the object's own shader `NPR_<full name>`. An image node is linked into the shader only while it has an image. The add-on swaps the images on those four nodes and their links into the shader; the rest of the layout is yours.

### The shader
| | |
|---|---|
| BASE | the split part's Mid color, flat |
| ALB | over BASE by its alpha (baked from the Original; erase it for the flat part colors) |
| TEX | over ALB by its alpha |
| NOR | bends the light before it is evaluated |
| Light | the part's ramp: Shadow, Mid, High. Painted ALB / TEX are shaded like the part (color x band / Mid) |
| Gloss | a highlight above the part's Gloss slider (its own scale: the highlight's strength) |
| Lights | every visible light counts, averaged (so 4 lights are not 4x as bright); Exposure scales it |
| SHD | gray: 0.5 changes nothing, darker pushes the light toward Shadow, lighter toward High |

Files made with an older version: **Check All Links** builds the new shader; the split parts stay.

## 02.Bake & Link Texture
Per object: the Original, the Cage, and Bake ALB + NOR (Cycles, Selected to Active, on `uv_normal` or else the active UV map).

## 03.LiveLink
The four textures of each object (show, load, folder, reload) and its Procreate file.
1. **Send to iPad** (one object, or **Send Selected to iPad**): the latest textures as one 8K PSD in `PPD_Procreate/To iPad`, also on the LiveLink page. From the top: `UV layout k<key>` 25 %, then the groups SHD (50 % gray, shown Overlay), TEX, ALB (transparent outside the UV islands), BASE (the parts' Mid, a guide), NOR (hidden).
2. Procreate: Import > Files > `PPD_Procreate/To iPad`. Paint inside the groups; add as many layers as you like.
3. Share > PSD > Save to Files > `PPD_Procreate` (or *Send to Blender* on the page). ALB, TEX, SHD and NOR come back merged; BASE is ignored.

The canvas name carries the object's key, so renaming the object or the .blend does not lose the link. A renamed canvas is still found by the key in its UV layout layer. Versions are the artist's: Send to iPad again for a fresh canvas (after a rebake or a new UV), the old one stays on the iPad.

**Rebake & Send** (beside Send to iPad): bakes ALB + NOR again from the Original (after a new UV or a change), then sends the fresh PSD.

**iPad Setup**: Set Up This PC, then in the iPad account box (under the PC address) **Make Account in Terminal**: a PowerShell window asks for the password twice and makes a local Windows account (`ppdipad` unless you type another name) that can only open `PPD_Procreate` and cannot sign in at the PC. One Windows prompt; **Generated Password** does the same without typing. The panel and the LiveLink page show its name and password with Copy buttons; the iPad logs in as Registered User with them (a Windows PIN never works over the network). The password is kept in Blender's config folder on this PC. **Test Password** checks it on the PC; X removes the account.

The address contains a key: do not share the QR code.

The page, the QR code and the shared folder all use the PC's name (for example `AUCO.local`), so a new IP number changes nothing. If the iPad does not find the name, type the number into **Address**.

## 04.Split Parts & Ramps
Edit Mode: select faces, **Add Split Part**. Each part, and the faces in no part, has a color bar: Shadow, Mid, High, and beside it Gloss (color and slider).
- The main color (Mid) is first in the part's header; the button beside the name fills the ramp from the Concept Palette (without one, it estimates the shades from the main color).
- Click a block for its color (with the eyedropper); drag a handle between two blocks left or right to move that border; + and - add or remove a shade (1 to 3).
- Files made with an older version get the new shader by themselves when opened; colors already set in the bar stay.
- Parts are one number per face (`PPD_PART`): a face is in one part only, the last one it was put in.
- The copy button gives a part's colors to all the other parts; the refresh button rebuilds the shader.

**Concept Palette** (Image Editor, N, tab PPD, in View, UV and Paint mode): **Pick Colors** takes the picture that editor shows; choose how many colors. The main colors come out in a row, similar hues side by side, dark to light. Drag a swatch onto a ramp block to use it. Transparent pixels do not count.

## 05.Unpacking
How ALB and TEX were blended in Procreate (the group's mode and opacity, or those of its only layer), kept and applied in the shader. Inside a group, layers, masks, clipping masks, opacity and blend modes are merged when the PSD arrives.

## 06.Quality of Life
For all set-up objects or the selected ones (the active one counts): **Light Color**, **Outline** (viewport and render), **Exposure** and **True Colors** (Standard view instead of AgX, so the ramp colors show as picked), which layers show (BASE, ALB, TEX, NOR, SHD) and **Solo** for one layer flat. The details (PC checks, activity log) show only with the Infos debug switch.
**Clean Up Files** moves to the Recycle Bin what nothing uses any more: textures of objects that are gone, `_previous` copies, sent PSDs (off by default) and LiveLink's temp files. Only files named after this .blend are touched.

## Install
`python install.py` copies the add-on into Blender 5.3 and reloads it; `python zip_addon.py` makes a zip.

## Tests
`blender -b --factory-startup -P tests/test_headless.py`, `tests/test_parts.py`, `tests/test_shader.py` (renders with EEVEE), `tests/test_unpacking.py` and `tests/test_palette.py`

License: GPL-3.0-or-later. 03.LiveLink is based on Procreate Live Link 1.0.0 (GPL-3.0-or-later).
