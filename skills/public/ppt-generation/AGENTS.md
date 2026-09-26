# PPT Generation

The skill instructions own the generation flow. The progress script stores a
plan-bound prefix of verified slide images in the mounted user workspace.
After an image model change, generation stops; a new request checks that
progress before continuing or explicitly restarting. The composition script's
progress-file option requires all slides to remain valid before writing a PPTX.
Keep resume and composition tests in the root skill test suite.
