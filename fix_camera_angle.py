import os
import glob
import re

def fix_worlds(directory, start_y=0, z=15, pitch=0.8, yaw=1.57):
    world_files = glob.glob(os.path.join(directory, "*.world"))
    print(f"Found {len(world_files)} world files in {directory}")

    gui_tag = f"""    <gui fullscreen='0'>
      <camera name='user_camera'>
        <pose>-2.25 {start_y} {z} 0 {pitch} {yaw}</pose>
        <view_controller>orbit</view_controller>
      </camera>
    </gui>"""

    for filepath in world_files:
        with open(filepath, 'r') as f:
            content = f.read()

        # Replace existing <gui> block entirely
        gui_pattern = re.compile(r"<gui.*?</gui>", re.DOTALL)
        if gui_pattern.search(content):
            content = gui_pattern.sub(gui_tag, content)
        else:
            # If no constraint occurs, add to end (before </world>)
            content = content.replace("</world>", gui_tag + "\n  </world>")

        with open(filepath, 'w') as f:
            f.write(content)

if __name__ == "__main__":
    barn_dir = "jackal_helper/worlds/BARN"
    if os.path.exists(barn_dir):
        # Focus beautifully tracking behind the robot at start.
        fix_worlds(barn_dir, start_y=-2, z=14, pitch=0.65, yaw=1.57)
    
    dynabarn_dir = "jackal_helper/worlds/DynaBARN"
    if os.path.exists(dynabarn_dir):
        # Different dynamic map origin mappings
        fix_worlds(dynabarn_dir, start_y=0, z=14, pitch=0.65, yaw=3.14)
                  
    print("Camera angles fixed successfully by overwriting existing guis!")
