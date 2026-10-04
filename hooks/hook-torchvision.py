"""Collect torchvision libraries loaded through torch.ops.load_library."""

from PyInstaller.utils.hooks import collect_dynamic_libs

binaries = collect_dynamic_libs(
	"torchvision",
	search_patterns=["*.so", "*.so.*", "*.dylib", "*.dll", "*.pyd"],
)