import json
from pathlib import Path

# Nombres de los archivos en orden
filenames = [
    "0-1-segment_1_1788555412.json",
    "1-2-segment_1_1788555546.json",
    "2-3-segment_1_1788555788.json",
    "3-4.06-_1788555951.json"
]

all_segments = []
offset = 0.0          # offset acumulado para el archivo actual
last_end = 0.0        # último tiempo final del segmento anterior (absoluto)
new_index = 1

for fname in filenames:
    with open(fname, 'r', encoding='utf-8') as f:
        data = json.load(f)

    segments = data.get("segments", [])
    if not segments:
        continue

    # Primer segmento del archivo actual
    first_start = segments[0]["start"]

    # Para el primer archivo, offset = 0; para los siguientes,
    # offset = last_end - first_start, para que el nuevo inicio coincida con last_end
    if offset == 0.0 and new_index == 1:
        offset = 0.0
    else:
        offset = last_end - first_start

    # Aplicar offset a todos los segmentos del archivo
    for seg in segments:
        new_seg = seg.copy()
        new_seg["start"] = round(seg["start"] + offset, 6)
        new_seg["end"] = round(seg["end"] + offset, 6)
        new_seg["index"] = new_index
        new_index += 1
        all_segments.append(new_seg)

    # Actualizar last_end con el final del último segmento de este archivo (ya offseteado)
    last_end = all_segments[-1]["end"]

# Construir el objeto fusionado (puedes ajustar los metadatos según necesites)
merged = {
    "transcript_id": "merged_audio",
    "source_file": "merged.wav",
    "language": "es-CL",
    "segments": all_segments,
    "total_duration_seconds": round(last_end, 6),
    "total_segments": len(all_segments)
}

# Guardar o imprimir el resultado
output_file = "merged_segments.json"
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(merged, f, indent=2, ensure_ascii=False)

print(f"Fusión completada. {len(all_segments)} segmentos, duración total {last_end:.3f} s.")
print(f"Resultado guardado en {output_file}")