# export_pixels_widget.py  (fixed)
import os, numpy as np, napari
from magicgui import magicgui
from magicgui.widgets import FileEdit

def _get_active_image_data(viewer):
    layer = viewer.layers.selection.active
    if layer is None:
        raise RuntimeError("Select an image layer first.")
    scale = tuple(getattr(layer, "scale", (1.0, 1.0)))
    return np.asarray(layer.data), (layer.name or "image"), scale

def _default_filename(layer_name: str, fmt: str) -> str:
    base = layer_name.replace(" ", "_") or "image"
    return base + ("_pixels.csv" if fmt == "triplets" else "_matrix.csv")

@magicgui(
    call_button="Export CSV",
    format={"label": "Format", "choices": ["triplets", "matrix"]},
    grayscale={"label": "Convert RGB→Gray"},
    normalize={"label": "Normalize 0..1"},
    use_physical={"label": "Use layer.scale for x,y"},
    output_path={
        "label": "Save as",
        "widget_type": FileEdit,   
        "mode": "w",               # write mode allowed here
        "filter": "*.csv",
    },
)
def export_widget(
    viewer: napari.Viewer,
    format: str = "triplets",
    grayscale: bool = True,
    normalize: bool = False,
    use_physical: bool = False,
    output_path: str = "",        # FileEdit returns a str path
):
    try:
        data, lname, scale = _get_active_image_data(viewer)

        # greyscale rgb calculation
        if grayscale and data.ndim == 3 and data.shape[-1] >= 3:
            R, G, B = data[..., 0], data[..., 1], data[..., 2]
            data = 0.299*R + 0.587*G + 0.114*B

        if data.ndim != 2:
            raise RuntimeError("Only 2-D images supported (convert stacks first).")

        A = data.astype(float, copy=False)
        if normalize:
            vmin, vmax = float(A.min()), float(A.max())
            A = (A - vmin)/(vmax - vmin) if vmax > vmin else np.zeros_like(A)

        if not output_path:
            output_path = os.path.abspath(_default_filename(lname, format))
        else:
            output_path = os.path.abspath(str(output_path))
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        if format == "matrix":
            np.savetxt(output_path, A, delimiter=",", fmt="%.6g")
        else:
            h, w = A.shape
            y, x = np.indices((h, w))
            if use_physical:
                # Napari's scale is (row, col); map to (y, x)
                sy = scale[0] if len(scale) >= 1 else 1.0
                sx = scale[1] if len(scale) >= 2 else 1.0
                x = x * sx
                y = y * sy
                header = "x(phys),y(phys),intensity"
                fmts = ["%.6g","%.6g","%.6g"]
            else:
                header = "x,y,intensity"
                fmts = ["%d","%d","%.6g"]
            arr = np.column_stack([x.ravel(), y.ravel(), A.ravel()])
            np.savetxt(output_path, arr, delimiter=",", fmt=fmts, header=header, comments="")

        print(f"✅ Saved → {output_path}")
        viewer.status = f"Saved CSV: {output_path}"
    except Exception as e:
        msg = f"Export failed: {e}"
        print("⚠️", msg)
        viewer.status = msg

def _install(viewer: napari.Viewer):
    viewer.window.add_dock_widget(export_widget, area="right", name="Export Pixels to CSV")
    # Prefill filename when layer changes
    @viewer.layers.selection.events.active.connect
    def _on_active(_=None):
        try:
            _, lname, _ = _get_active_image_data(viewer)
            export_widget.output_path.value = os.path.abspath(
                _default_filename(lname, export_widget.format.value)
            )
        except Exception:
            pass
    # initialize once
    try:
        _, lname, _ = _get_active_image_data(viewer)
        export_widget.output_path.value = os.path.abspath(
            _default_filename(lname, export_widget.format.value)
        )
    except Exception:
        pass

if __name__ == "__main__":
    v = napari.Viewer()
    _install(v)
    napari.run()
else:
    gv = globals().get("viewer", None)
    if isinstance(gv, napari.Viewer):
        _install(gv)
