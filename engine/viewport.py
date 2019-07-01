from time import time
from .. import export
from ..draw.viewport import FrameBuffer
from ..utils import render as utils_render

import bpy
from ..bin import pyluxcore
from .. import utils


# Executed in separate thread
# TODO handle the case that the user cancelled the viewport render (engine will be deleted)
#  maybe save a reference to this thread in engine and join it in engine.__del__()?
def start_session(engine):
    try:
        engine.session.Start()
        engine.viewport_start_time = time()
    except Exception as error:
        del engine.session
        engine.session = None
        # Reset the exporter to invalidate all caches
        engine.exporter = None

        engine.update_stats("Error: ", str(error))
        # scene.luxcore.errorlog.add_error(error)  # TODO 2.8

        import traceback
        traceback.print_exc()

    # TODO use lock when changing starting_session? Not strictly necessary
    #  due to CPython implementation details, but might be cleaner
    engine.starting_session = False


def view_update(engine, context, depsgraph, changes=None):
    if engine.starting_session:
        # Prevent deadlock
        return

    scene = depsgraph.scene_eval

    if engine.framebuffer:
        engine.framebuffer.reset_denoiser()

    #scene.luxcore.errorlog.clear()  # TODO 2.8

    if engine.session is None:
        print("=" * 50)
        print("[Engine/Viewport] New session")
        try:
            engine.update_stats("Creating Render Session...", "")
            engine.exporter = export.Exporter(scene)
            engine.session = engine.exporter.create_session(depsgraph, context)
            # Start in separate thread to avoid blocking the UI
            engine.starting_session = True
            import _thread
            _thread.start_new_thread(start_session, (engine,))
        except Exception as error:
            del engine.session
            engine.session = None
            # Reset the exporter to invalidate all caches
            engine.exporter = None

            engine.update_stats("Error: ", str(error))
            # scene.luxcore.errorlog.add_error(error)  # TODO 2.8

            import traceback
            traceback.print_exc()
        return

    if changes is None:
        changes = engine.exporter.get_changes(depsgraph, context)

    # TODO 2.8 remove
    # if changes & export.Change.CONFIG:
    #     # Film resize requires a new framebuffer
    #     engine.framebuffer = FrameBuffer(context)

    # We have to re-assign the session because it might have been replaced due to filmsize change
    engine.session = engine.exporter.update(depsgraph, context, engine.session, changes)

    if changes:
        engine.viewport_start_time = time()

last_cam_str = ""

def view_draw(engine, context, depsgraph):
    scene = depsgraph.scene_eval

    if not engine.framebuffer or engine.framebuffer.needs_replacement(context, scene):
        print("new framebuffer")
        engine.framebuffer = FrameBuffer(engine, context, scene)

    if engine.session and not engine.starting_session:
        # hacky camera update
        from ..export import camera
        cam_props = camera.convert(None, scene, context)
        global last_cam_str
        new_cam_str = str(cam_props)
        if new_cam_str != last_cam_str:
            last_cam_str = new_cam_str
            luxcore_scene = engine.session.GetRenderConfig().GetScene()
            engine.session.BeginSceneEdit()
            luxcore_scene.Parse(cam_props)
            engine.session.EndSceneEdit()
            import time
            time.sleep(0.1)

        try:
            engine.session.UpdateStats()
        except RuntimeError as error:
            print("[Engine/Viewport] Error during UpdateStats():", error)
        engine.session.WaitNewFrame()
        engine.framebuffer.update(engine.session, scene)
        engine.framebuffer.draw(engine, context, scene)
    engine.tag_redraw()

    # scene = context.scene
    #
    # # Check for changes because some actions in Blender (e.g. moving the viewport
    # # camera) do not trigger a view_update() call, but only a view_draw() call.
    # changes = engine.exporter.get_changes(context)
    #
    # if changes & export.Change.REQUIRES_VIEW_UPDATE:
    #     engine.tag_redraw()
    #     view_update(engine, context, changes)
    #     return
    # elif changes & export.Change.CAMERA:
    #     # Only update in view_draw if it is a camera update,
    #     # for everything else we call view_update().
    #     # We have to re-assign the session because it might have been
    #     # replaced due to filmsize change.
    #     engine.session = engine.exporter.update(context, engine.session, export.Change.CAMERA)
    #     engine.viewport_start_time = time()
    #
    # # On startup we don't have a framebuffer yet
    # if engine.framebuffer is None:
    #     engine.framebuffer = FrameBuffer(context)
    # framebuffer = engine.framebuffer
    #
    # # Check if we need to pause the viewport render
    # # (note: the LuxCore stat "stats.renderengine.time" is not reliable here)
    # rendered_time = time() - engine.viewport_start_time
    # halt_time = scene.luxcore.viewport.halt_time
    # status_message = ""
    #
    # if rendered_time > halt_time:
    #     if not engine.session.IsInPause():
    #         print("[Engine/Viewport] Pausing session")
    #         engine.session.Pause()
    #     status_message = "(Paused)"
    #
    #     if framebuffer.denoiser_result_cached:
    #         status_message = "(Paused, Denoiser Done)"
    #     else:
    #         if framebuffer.is_denoiser_active():
    #             if framebuffer.is_denoiser_done():
    #                 status_message = "(Paused, Denoiser Done)"
    #                 framebuffer.load_denoiser_result(scene) # TODO warning, now scene instead of context!
    #             else:
    #                 status_message = "(Paused, Denoiser Working ...)"
    #                 engine.tag_redraw()
    #         elif context.scene.luxcore.viewport.denoise:
    #             try:
    #                 framebuffer.start_denoiser(engine.session)
    #                 engine.tag_redraw()
    #             except Exception as error:
    #                 status_message = "Could not start denoiser: %s" % error
    # else:
    #     # Not in pause yet, keep drawing
    #     try:
    #         engine.session.UpdateStats()
    #     except RuntimeError as error:
    #         print("[Engine/Viewport] Error during UpdateStats():", error)
    #     engine.session.WaitNewFrame()
    #     framebuffer.update(engine.session, scene) # TODO warning, now scene instead of context!
    #     framebuffer.reset_denoiser()
    #     engine.tag_redraw()
    #
    # framebuffer.draw(engine, context)
    #
    # # Show formatted statistics in Blender UI
    # config = engine.session.GetRenderConfig()
    # stats = engine.session.GetStats()
    # pretty_stats = utils_render.get_pretty_stats(config, stats, scene, context)
    # engine.update_stats(pretty_stats, status_message)
