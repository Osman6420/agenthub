"""Migration-backed search geometries for the shared vector store.

Adding a geometry requires a schema migration with its fixed expression index.
These SQL fragments are closed constants, never interpolated from profile input.
Legacy per-generation stores retain their own geometry during migration.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SharedGeometry:
    dimensions: int
    representation: str
    cast: str
    predicate: str
    index_name: str


SHARED_GEOMETRIES = (
    SharedGeometry(
        64,
        "vector",
        "vector(64)",
        "dimensions = 64 AND representation = 'vector'",
        "shared_vec_64_cos",
    ),
    SharedGeometry(
        768,
        "vector",
        "vector(768)",
        "dimensions = 768 AND representation = 'vector'",
        "shared_vec_768_cos",
    ),
    SharedGeometry(
        1536,
        "vector",
        "vector(1536)",
        "dimensions = 1536 AND representation = 'vector'",
        "shared_vec_1536_cos",
    ),
    SharedGeometry(
        3072,
        "halfvec",
        "halfvec(3072)",
        "dimensions = 3072 AND representation = 'halfvec'",
        "shared_half_3072_cos",
    ),
    SharedGeometry(
        4000,
        "halfvec",
        "halfvec(4000)",
        "dimensions = 4000 AND representation = 'halfvec'",
        "shared_half_4000_cos",
    ),
)


def shared_geometry(representation: str, dimensions: int | None) -> SharedGeometry:
    if isinstance(dimensions, bool) or not isinstance(dimensions, int):
        raise ValueError("SHARED_VECTOR_GEOMETRY_UNSUPPORTED")
    for geometry in SHARED_GEOMETRIES:
        if geometry.representation == representation and geometry.dimensions == dimensions:
            return geometry
    raise ValueError("SHARED_VECTOR_GEOMETRY_UNSUPPORTED")
