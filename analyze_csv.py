import csv
import os

# Path to the CSV on Desktop
desktop = os.path.join(os.path.expanduser("~"), "Desktop")
csv_path = os.path.join(desktop, "full_image_pixels_new.csv")

max_intensity = float("-inf")
min_intensity = float("inf")
large_vals=[]

with open(csv_path, "r", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        try:
            value = float(row["intensity"])
            if value > max_intensity:
                max_intensity = value
            if value < min_intensity:
                min_intensity = value
            #if value < 80:
                #large_vals.append(value)
                #print(row)
            
        except ValueError:
            continue  # skip rows with non-numeric values

print(f"Maximum intensity: {max_intensity}")
print(f"Minimum intensity: {min_intensity}")
