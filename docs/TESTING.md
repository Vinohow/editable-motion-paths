# QA / Testing Matrix

Use this document for release candidates and bug reproduction. Record results separately per OS/Blender build.

Suggested status values: `PASS`, `FAIL`, `BLOCKED`, `NOT TESTED`.

## Test environment header

Record before every full run:

| Field                      | Value                     |
| -------------------------- | ------------------------- |
| Add-on version             |                           |
| Blender version/build hash |                           |
| OS/version                 |                           |
| GPU                        |                           |
| UI scale                   |                           |
| Input device               | mouse / tablet / trackpad |
| Fresh Blender preferences? | yes/no                    |

---

## A. Packaging and lifecycle

- [ ] A01 - Install release ZIP with **Install from Disk**.
- [ ] A02 - Extension appears as `Editable Motion Paths`.
- [ ] A03 - Enable extension without Python error.
- [ ] A04 - Motion Path sidebar appears in 3D View.
- [ ] A05 - Save preferences/restart Blender; extension remains usable.
- [ ] A06 - Disable extension; overlays and controls disappear cleanly.
- [ ] A07 - Re-enable extension; overlays return correctly.
- [ ] A08 - Uninstall extension without crash.
- [ ] A09 - Reinstall same ZIP without stale UI/runtime state.
- [ ] A10 - Open a new `.blend`; no state leaks from previous scene.

## B. Basic path generation

- [ ] B01 - New cube, Location key at frame 1 and 30 → path appears.
- [ ] B02 - Add third Location key → path updates.
- [ ] B03 - Remove middle key → path updates.
- [ ] B04 - Remove all Location keys → path disappears.
- [ ] B05 - Recreate keys → path returns.
- [ ] B06 - Object with Rotation-only animation → no false Location path.
- [ ] B07 - Switch active object → path context updates.
- [ ] B08 - Deselect all → no stale interactive keys.

## C. Key selection and drag discrimination

- [ ] C01 - Single click key selects it without changing position.
- [ ] C02 - Very small mouse jitter on click does not move key.
- [ ] C03 - Deliberate drag moves key.
- [ ] C04 - Repeated clicks never randomly grab a handle.
- [ ] C05 - Key center has priority over overlapping handle hit regions.
- [ ] C06 - Click empty space does not unexpectedly edit path.
- [ ] C07 - Rotate/pan/zoom viewport after selection; selection remains coherent.
- [ ] C08 - Click another Blender object; normal viewport selection remains possible.

## D. Key movement

- [ ] D01 - Drag key in perspective view.
- [ ] D02 - Drag key in orthographic view.
- [ ] D03 - Drag key while zoomed very close.
- [ ] D04 - Drag key while zoomed far away.
- [ ] D05 - Path follows continuously during drag.
- [ ] D06 - On release, final path matches final key position.
- [ ] D07 - Undo restores previous key/path state.
- [ ] D08 - Redo restores moved state.
- [ ] D09 - Repeat move/undo 20 times without crash or drift.

## E. Multi-selection

- [ ] E01 - Shift-click second key adds to selection.
- [ ] E02 - Shift-click selected key removes it.
- [ ] E03 - Multi-selected keys are visually identifiable.
- [ ] E04 - Drag selected key moves the full selected set.
- [ ] E05 - Relative offsets between selected keys remain correct.
- [ ] E06 - Undo restores all moved keys.
- [ ] E07 - Selection from another object does not corrupt active-object editing.

## F. Corner / smooth toggle

- [ ] F01 - Alt-click smooth key → Vector/corner.
- [ ] F02 - Alt-click corner key → smooth/manual state.
- [ ] F03 - Toggle does not move key position.
- [ ] F04 - Corner has visibly sharp trajectory behavior.
- [ ] F05 - Smooth state has visibly continuous tangent behavior.
- [ ] F06 - Undo/Redo restores handle type and path shape.
- [ ] F07 - Repeated toggle does not accumulate path drift.

## G. Alt-drag manual tangent

- [ ] G01 - Start from corner; Alt-drag produces manual smooth tangent.
- [ ] G02 - Drag direction controls tangent direction.
- [ ] G03 - Drag distance controls tangent magnitude.
- [ ] G04 - Tiny Alt-click without drag performs quick toggle rather than arbitrary tangent draw.
- [ ] G05 - Alt-drag does not accidentally move the key position.
- [ ] G06 - Resulting path is stable after release.
- [ ] G07 - Undo restores pre-drag corner/handle state.
- [ ] G08 - Redo restores manual tangent.

## H. Handle editing

- [ ] H01 - Selecting a key exposes handles when enabled.
- [ ] H02 - Click handle selects handle only.
- [ ] H03 - Drag left handle changes left spatial tangent.
- [ ] H04 - Drag right handle changes right spatial tangent.
- [ ] H05 - Key does not move while only a handle is dragged.
- [ ] H06 - Handle remains selectable when geometry is in front/behind.
- [ ] H07 - Handle visual position follows edited tangent.
- [ ] H08 - Handle edit path update is continuous.
- [ ] H09 - Undo/Redo works for handle edit.
- [ ] H10 - Auto/Vector direct manipulation converts to a manual state predictably when needed.

## I. Axis constraints

For both **keys** and **handles**:

- [ ] I01 - `X` constrains to X.
- [ ] I02 - `Y` constrains to Y.
- [ ] I03 - `Z` constrains to Z.
- [ ] I04 - `Shift+X` constrains to YZ plane.
- [ ] I05 - `Shift+Y` constrains to XZ plane.
- [ ] I06 - `Shift+Z` constrains to XY plane.
- [ ] I07 - Repeating same constraint returns to free movement.
- [ ] I08 - Visual guide matches active constraint.
- [ ] I09 - Global constraint uses world axes.
- [ ] I10 - Local constraint follows object local axes.
- [ ] I11 - Constraint does not corrupt handle timing values.

## J. Snap

- [ ] J01 - Set Snap Increment to 0.1; Ctrl-drag produces expected increments.
- [ ] J02 - Change increment; new value is used.
- [ ] J03 - Snap + axis constraint works together.
- [ ] J04 - Snap + multi-selected key move remains coherent.
- [ ] J05 - Releasing Ctrl returns to unsnapped behavior.

## K. Auto Key / live update

- [ ] K01 - Enable Auto Key at an existing keyed frame; G-move object → path follows during manipulation.
- [ ] K02 - Enable Auto Key at a frame without a Location key; G-move object → live path preview is sensible.
- [ ] K03 - Validate transform → final inserted/updated key and path agree.
- [ ] K04 - Cancel transform → preview returns to original path.
- [ ] K05 - Undo after Auto Key move restores path immediately.
- [ ] K06 - Redo restores it.
- [ ] K07 - Rapid repeated Auto Key transforms do not flicker or leave stale paths.

## L. Direction arrows

- [ ] L01 - Direction arrows point in temporal animation direction.
- [ ] L02 - Reverse key positions while frame order stays same → arrow direction remains time-correct.
- [ ] L03 - Change arrow spacing → density changes.
- [ ] L04 - Change arrow size → visual size changes.
- [ ] L05 - Disable arrows → no arrow remains.
- [ ] L06 - Arrows follow edited curve after key/handle manipulation.

## M. Past/future visualization

- [ ] M01 - Enable time split; path before current frame uses past color.
- [ ] M02 - Path after current frame uses future color.
- [ ] M03 - Scrub current frame; split point updates.
- [ ] M04 - Disable split; path uses expected unified appearance.
- [ ] M05 - Change both colors on Windows.
- [ ] M06 - Change both colors on macOS.

## N. Key / handle appearance

- [ ] N01 - Change smooth-key color.
- [ ] N02 - Change corner-key color.
- [ ] N03 - Change selected-key color.
- [ ] N04 - Change key size from minimum to maximum.
- [ ] N05 - Change handle size from minimum to maximum.
- [ ] N06 - Toggle key outline.
- [ ] N07 - Change outline thickness.
- [ ] N08 - Change line width.
- [ ] N09 - Changes update immediately on Windows.
- [ ] N10 - Changes update immediately on macOS/Retina.
- [ ] N11 - Test Blender UI scale 100%.
- [ ] N12 - Test Blender UI scale 150% or nearest available.
- [ ] N13 - Test Blender UI scale 200% or nearest available.

## O. Labels / badges / samples

- [ ] O01 - Enable frame labels; values match key frames.
- [ ] O02 - Disable frame labels; no stale text remains.
- [ ] O03 - Change label size.
- [ ] O04 - Change label color.
- [ ] O05 - Enable key-type badges.
- [ ] O06 - Vector/Aligned/Auto/Free badge matches actual state where applicable.
- [ ] O07 - Disable badges; clean viewport.
- [ ] O08 - Enable intermediate samples.
- [ ] O09 - Change sample point size.

## P. X-Ray and depth

- [ ] P01 - X-Ray on → path/controls remain readable through geometry.
- [ ] P02 - X-Ray off → depth behavior is sensible.
- [ ] P03 - Key/handle controls remain pickable in intended direct-edit cases.
- [ ] P04 - No Z-fighting/flicker while orbiting camera.

## Q. Display scope

- [ ] Q01 - Active Object mode shows only intended active path.
- [ ] Q02 - Selected Objects mode shows intended selected paths.
- [ ] Q03 - Change active object among selection; active styling/context updates.
- [ ] Q04 - Deselect an object; its selected-only path disappears when expected.
- [ ] Q05 - Delete animated object; no orphan overlay/gizmo remains.
- [ ] Q06 - Duplicate animated object; both paths behave correctly.
- [ ] Q07 - Rename object; runtime selection/cache remains valid.

## R. Range modes

- [ ] R01 - Between Keys uses expected first/last relevant key.
- [ ] R02 - Around Current Frame uses configured Before frames.
- [ ] R03 - Around Current Frame uses configured After frames.
- [ ] R04 - Scene mode respects scene start/end.
- [ ] R05 - Scrubbing updates windowed range correctly.
- [ ] R06 - Zero Before/After edge cases behave safely.

## S. Sampling / performance controls

- [ ] S01 - Minimum step 1 produces expected detail.
- [ ] S02 - Larger minimum step reduces samples.
- [ ] S03 - Adaptive Sampling on respects Max Samples.
- [ ] S04 - Adaptive Sampling off remains stable.
- [ ] S05 - Max Samples minimum value works.
- [ ] S06 - Max Samples high value does not crash.

## T. Performance stress

Record viewport FPS qualitatively or quantitatively when possible.

- [ ] T01 - 2 keys / 250-frame range.
- [ ] T02 - 50 keys / 250 frames.
- [ ] T03 - 200 keys / 1000 frames.
- [ ] T04 - 2000-frame scene range.
- [ ] T05 - 10 animated selected objects.
- [ ] T06 - 50 animated selected objects (if practical).
- [ ] T07 - Orbit viewport while path is displayed.
- [ ] T08 - Scrub timeline rapidly.
- [ ] T09 - Play animation while paths are visible.
- [ ] T10 - No runaway CPU usage after interaction stops.

## U. Blender editor interoperability

- [ ] U01 - Edit Location key in Dope Sheet → path refreshes.
- [ ] U02 - Edit Location value in Graph Editor → path refreshes.
- [ ] U03 - Change interpolation/handles in Graph Editor → path refreshes.
- [ ] U04 - Delete key in Dope Sheet → path refreshes.
- [ ] U05 - Undo in Graph Editor → viewport path follows.
- [ ] U06 - Change workspace → no orphan/stale overlay.
- [ ] U07 - Return to original workspace → controls valid.
- [ ] U08 - Open/close N-panel during editing → no crash.

## V. Parenting / constraints / advanced animation

These are exploratory until exact support is declared.

- [ ] V01 - Static parent transform.
- [ ] V02 - Animated parent Location.
- [ ] V03 - Parent rotation affecting child world path.
- [ ] V04 - Copy Location constraint.
- [ ] V05 - Child Of constraint.
- [ ] V06 - Driver affecting Location.
- [ ] V07 - NLA strip influencing Location.
- [ ] V08 - Multiple action/slot configurations.

For any mismatch, attach a minimal scene and label the report `evaluation`.

## W. Save/load

- [ ] W01 - Save `.blend` with extension active.
- [ ] W02 - Close/reopen Blender and file.
- [ ] W03 - Animation data is unchanged/correct.
- [ ] W04 - Overlay runtime state rebuilds safely.
- [ ] W05 - No stale selection points to deleted data.

## X. Crash regression

- [ ] X01 - Rapidly select/drag handles for 2 minutes.
- [ ] X02 - Rapidly switch keys while viewport is redrawing.
- [ ] X03 - Change sidebar settings during normal interaction.
- [ ] X04 - Undo/Redo rapidly after handle edits.
- [ ] X05 - Disable extension after several edits.
- [ ] X06 - Re-enable and continue editing.
- [ ] X07 - No `EXCEPTION_ACCESS_VIOLATION` / segfault.

## Y. Input devices

- [ ] Y01 - Standard mouse.
- [ ] Y02 - Trackpad (macOS if available).
- [ ] Y03 - Pen/tablet if available.
- [ ] Y04 - Modifier keys recognized reliably on macOS.
- [ ] Y05 - Modifier keys recognized reliably on Windows.

## Z. Release acceptance

A release candidate should not be marked stable if any of these fail reproducibly:

- [ ] Z01 - Install/enable/restart lifecycle.
- [ ] Z02 - Basic path generation.
- [ ] Z03 - Click selects without moving.
- [ ] Z04 - Key drag.
- [ ] Z05 - Handle drag.
- [ ] Z06 - Alt-click corner/smooth.
- [ ] Z07 - Alt-drag tangent.
- [ ] Z08 - Undo/Redo.
- [ ] Z09 - Auto Key live update.
- [ ] Z10 - No reproducible Blender crash.
- [ ] Z11 - Windows appearance controls.
- [ ] Z12 - macOS appearance controls.
