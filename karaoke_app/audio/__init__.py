"""Audio subsystem.

Deliberately empty of imports: pulling in ``separation`` drags torch and demucs
into the process, which costs seconds of start-up. Import the submodule you
need, and let the job manager load the heavy ones on a worker thread.
"""
