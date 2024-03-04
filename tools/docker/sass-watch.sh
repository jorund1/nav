#!/usr/bin/env bash
# ensures CSS files are rebuilt on SASS file changes
#
cd /source
while inotifywait -e modify -e move -e create -e delete -r --exclude \# /source/python/nav/web/sass
do
  (cd python/nav/web/static/js && npm run build:sass:prod)
done
