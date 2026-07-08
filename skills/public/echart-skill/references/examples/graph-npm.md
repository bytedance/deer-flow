# graph-npm

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=graph-npm
**Chart Type:** `graph`

## User Data Requirements

Columns needed: need **nodes** [{name,...}] + **links/edges** [{source,target}]

## Data Arrays — Replacement Guide

The code contains **0 data array(s)** to replace:


## External Data Format

This example uses external data. Format from `npmdepgraph.min10.json`:

```json
[
  {
    "color": "#4f19c7",
    "label": "jquery",
    "attributes": {},
    "y": -404.26147,
    "x": -739.36383,
    "id": "jquery",
    "size": 4.7252817
  },
  {
    "color": "#c71969",
    "label": "backbone",
    "attributes": {},
    "y": -862.7517,
    "x": -134.2215,
    "id": "backbone",
    "size": 6.1554675
  },
  {
    "color": "#c71969",
    "label": "underscore",
    "attributes": {},
    "y": -734.4221,
    "x": -75.53079,
    "id": "underscore",
    "size": 100.0
  }
]
```

Agent: build DuckDB query to produce matching data structure.
## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: NPM Dependencies
category: graph
titleCN: NPM 依赖关系图
difficulty: 9
*/
myChart.showLoading();
var json = {
  "nodes": [
    {
      "color": "#4f19c7",
      "label": "jquery",
      "attributes": {},
      "y": -404.26147,
      "x": -739.36383,
      "id": "jquery",
      "size": 4.7252817
    },
    {
      "color": "#c71969",
      "label": "backbone",
      "attributes": {},
      "y": -862.7517,
      "x": -134.2215,
      "id": "backbone",
      "size": 6.1554675
    },
    {
      "color": "#c71969",
      "label": "underscore",
      "attributes": {},
      "y": -734.4221,
      "x": -75.53079,
      "id": "underscore",
      "size": 100.0
    },
    {
      "color": "#c71969",
      "label": "faye",
      "attributes": {},
      "y": 624.50604,
      "x": -818.97516,
      "id": "faye",
      "size": 0.67816025
    },
    {
      "color": "#c71919",
      "label": "socket.io",
      "attributes": {},
      "y": 120.37976,
      "x": -710.59204,
      "id": "socket.io",
      "size": 19.818306
    },
    {
      "color": "#c71969",
      "label": "requirejs",
      "attributes": {},
      "y": -612.5541,
      "x": 71.52897,
      "id": "requirejs",
      "size": 4.0862627
    },
    {
      "color": "#c71969",
      "label": "amdefine",
      "attributes": {},
      "y": -556.3107,
      "x": 1202.1166,
      "id": "amdefine",
      "size": 2.3822114
    },
    {
      "color": "#1984c7",
      "label": "mongoose",
      "attributes": {},
      "y": 378.15536,
      "x": -1150.2018,
      "id": "mongoose",
      "size": 10.81118
    },
    // ... (716 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
      ],
  "edges": [
    {
      "sourceID": "jquery",
      "attributes": {},
      "targetID": "jsdom",
      "size": 1
    },
    {
      "sourceID": "jquery",
      "attributes": {},
      "targetID": "xmlhttprequest",
      "size": 1
    },
    {
      "sourceID": "jquery",
      "attributes": {},
      "targetID": "htmlparser",
      "size": 1
    },
    {
      "sourceID": "jquery",
      "attributes": {},
      "targetID": "contextify",
      "size": 1
    },
    {
      "sourceID": "backbone",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "faye",
      "attributes": {},
      "targetID": "faye-websocket",
      "size": 1
    },
    {
      "sourceID": "faye",
      "attributes": {},
      "targetID": "cookiejar",
      "size": 1
    },
    {
      "sourceID": "socket.io",
      "attributes": {},
      "targetID": "redis",
      "size": 1
    },
    {
      "sourceID": "socket.io",
      "attributes": {},
      "targetID": "socket.io-client",
      "size": 1
    },
    {
      "sourceID": "mongoose",
      "attributes": {},
      "targetID": "mongodb",
      "size": 1
    },
    {
      "sourceID": "mongoose",
      "attributes": {},
      "targetID": "hooks",
      "size": 1
    },
    {
      "sourceID": "mongoose",
      "attributes": {},
      "targetID": "ms",
      "size": 1
    },
    {
      "sourceID": "cheerio",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "cheerio",
      "attributes": {},
      "targetID": "htmlparser2",
      "size": 1
    },
    {
      "sourceID": "cheerio",
      "attributes": {},
      "targetID": "entities",
      "size": 1
    },
    {
      "sourceID": "express",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "express",
      "attributes": {},
      "targetID": "connect",
      "size": 1
    },
    {
      "sourceID": "express",
      "attributes": {},
      "targetID": "commander",
      "size": 1
    },
    {
      "sourceID": "express",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "express",
      "attributes": {},
      "targetID": "cookie",
      "size": 1
    },
    {
      "sourceID": "express",
      "attributes": {},
      "targetID": "send",
      "size": 1
    },
    {
      "sourceID": "express",
      "attributes": {},
      "targetID": "methods",
      "size": 1
    },
    {
      "sourceID": "express",
      "attributes": {},
      "targetID": "buffer-crc32",
      "size": 1
    },
    {
      "sourceID": "express",
      "attributes": {},
      "targetID": "fresh",
      "size": 1
    },
    {
      "sourceID": "connect",
      "attributes": {},
      "targetID": "bytes",
      "size": 1
    },
    {
      "sourceID": "connect",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "connect",
      "attributes": {},
      "targetID": "qs",
      "size": 1
    },
    {
      "sourceID": "connect",
      "attributes": {},
      "targetID": "cookie",
      "size": 1
    },
    {
      "sourceID": "connect",
      "attributes": {},
      "targetID": "send",
      "size": 1
    },
    {
      "sourceID": "connect",
      "attributes": {},
      "targetID": "formidable",
      "size": 1
    },
    {
      "sourceID": "connect",
      "attributes": {},
      "targetID": "methods",
      "size": 1
    },
    {
      "sourceID": "connect",
      "attributes": {},
      "targetID": "buffer-crc32",
      "size": 1
    },
    {
      "sourceID": "connect",
      "attributes": {},
      "targetID": "fresh",
      "size": 1
    },
    {
      "sourceID": "connect",
      "attributes": {},
      "targetID": "pause",
      "size": 1
    },
    {
      "sourceID": "temp",
      "attributes": {},
      "targetID": "rimraf",
      "size": 1
    },
    {
      "sourceID": "request",
      "attributes": {},
      "targetID": "node-uuid",
      "size": 1
    },
    {
      "sourceID": "request",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "request",
      "attributes": {},
      "targetID": "qs",
      "size": 1
    },
    {
      "sourceID": "request",
      "attributes": {},
      "targetID": "form-data",
      "size": 1
    },
    {
      "sourceID": "event-stream",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "event-stream",
      "attributes": {},
      "targetID": "duplexer",
      "size": 1
    },
    {
      "sourceID": "event-stream",
      "attributes": {},
      "targetID": "split",
      "size": 1
    },
    {
      "sourceID": "event-stream",
      "attributes": {},
      "targetID": "pause-stream",
      "size": 1
    },
    {
      "sourceID": "event-stream",
      "attributes": {},
      "targetID": "map-stream",
      "size": 1
    },
    {
      "sourceID": "event-stream",
      "attributes": {},
      "targetID": "stream-combiner",
      "size": 1
    },
    {
      "sourceID": "event-stream",
      "attributes": {},
      "targetID": "from",
      "size": 1
    },
    {
      "sourceID": "log4js",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "log4js",
      "attributes": {},
      "targetID": "semver",
      "size": 1
    },
    {
      "sourceID": "log4js",
      "attributes": {},
      "targetID": "readable-stream",
      "size": 1
    },
    {
      "sourceID": "optimist",
      "attributes": {},
      "targetID": "wordwrap",
      "size": 1
    },
    {
      "sourceID": "mocha",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "mocha",
      "attributes": {},
      "targetID": "commander",
      "size": 1
    },
    {
      "sourceID": "mocha",
      "attributes": {},
      "targetID": "glob",
      "size": 1
    },
    {
      "sourceID": "mocha",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "mocha",
      "attributes": {},
      "targetID": "jade",
      "size": 1
    },
    {
      "sourceID": "mocha",
      "attributes": {},
      "targetID": "growl",
      "size": 1
    },
    {
      "sourceID": "mocha",
      "attributes": {},
      "targetID": "ms",
      "size": 1
    },
    {
      "sourceID": "mocha",
      "attributes": {},
      "targetID": "diff",
      "size": 1
    },
    {
      "sourceID": "prompt",
      "attributes": {},
      "targetID": "read",
      "size": 1
    },
    {
      "sourceID": "prompt",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "prompt",
      "attributes": {},
      "targetID": "winston",
      "size": 1
    },
    {
      "sourceID": "prompt",
      "attributes": {},
      "targetID": "utile",
      "size": 1
    },
    {
      "sourceID": "prompt",
      "attributes": {},
      "targetID": "revalidator",
      "size": 1
    },
    {
      "sourceID": "commander",
      "attributes": {},
      "targetID": "keypress",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "lodash",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "dateformat",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "underscore.string",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "minimatch",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "nopt",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "rimraf",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "which",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "glob",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "coffee-script",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "findup-sync",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "eventemitter2",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "iconv-lite",
      "size": 1
    },
    {
      "sourceID": "grunt",
      "attributes": {},
      "targetID": "js-yaml",
      "size": 1
    },
    {
      "sourceID": "grunt-contrib-less",
      "attributes": {},
      "targetID": "less",
      "size": 1
    },
    {
      "sourceID": "grunt-contrib-less",
      "attributes": {},
      "targetID": "grunt-lib-contrib",
      "size": 1
    },
    {
      "sourceID": "grunt-contrib-jshint",
      "attributes": {},
      "targetID": "jshint",
      "size": 1
    },
    {
      "sourceID": "grunt-contrib-uglify",
      "attributes": {},
      "targetID": "uglify-js",
      "size": 1
    },
    {
      "sourceID": "grunt-contrib-uglify",
      "attributes": {},
      "targetID": "grunt-lib-contrib",
      "size": 1
    },
    {
      "sourceID": "grunt-contrib-watch",
      "attributes": {},
      "targetID": "gaze",
      "size": 1
    },
    {
      "sourceID": "grunt-contrib-watch",
      "attributes": {},
      "targetID": "tiny-lr",
      "size": 1
    },
    {
      "sourceID": "http-proxy",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "http-proxy",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "http-proxy",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "http-proxy",
      "attributes": {},
      "targetID": "utile",
      "size": 1
    },
    {
      "sourceID": "mongodb",
      "attributes": {},
      "targetID": "bson",
      "size": 1
    },
    {
      "sourceID": "minimatch",
      "attributes": {},
      "targetID": "lru-cache",
      "size": 1
    },
    {
      "sourceID": "nopt",
      "attributes": {},
      "targetID": "abbrev",
      "size": 1
    },
    {
      "sourceID": "rimraf",
      "attributes": {},
      "targetID": "graceful-fs",
      "size": 1
    },
    {
      "sourceID": "tar",
      "attributes": {},
      "targetID": "fstream",
      "size": 1
    },
    {
      "sourceID": "tar",
      "attributes": {},
      "targetID": "inherits",
      "size": 1
    },
    {
      "sourceID": "fstream",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "fstream",
      "attributes": {},
      "targetID": "graceful-fs",
      "size": 1
    },
    {
      "sourceID": "fstream",
      "attributes": {},
      "targetID": "rimraf",
      "size": 1
    },
    {
      "sourceID": "fstream",
      "attributes": {},
      "targetID": "inherits",
      "size": 1
    },
    {
      "sourceID": "node-gyp",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "node-gyp",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "node-gyp",
      "attributes": {},
      "targetID": "semver",
      "size": 1
    },
    {
      "sourceID": "node-gyp",
      "attributes": {},
      "targetID": "graceful-fs",
      "size": 1
    },
    {
      "sourceID": "node-gyp",
      "attributes": {},
      "targetID": "minimatch",
      "size": 1
    },
    {
      "sourceID": "node-gyp",
      "attributes": {},
      "targetID": "nopt",
      "size": 1
    },
    {
      "sourceID": "node-gyp",
      "attributes": {},
      "targetID": "rimraf",
      "size": 1
    },
    {
      "sourceID": "node-gyp",
      "attributes": {},
      "targetID": "which",
      "size": 1
    },
    {
      "sourceID": "node-gyp",
      "attributes": {},
      "targetID": "tar",
      "size": 1
    },
    {
      "sourceID": "node-gyp",
      "attributes": {},
      "targetID": "fstream",
      "size": 1
    },
    {
      "sourceID": "node-gyp",
      "attributes": {},
      "targetID": "npmlog",
      "size": 1
    },
    {
      "sourceID": "node-gyp",
      "attributes": {},
      "targetID": "glob",
      "size": 1
    },
    {
      "sourceID": "node-gyp",
      "attributes": {},
      "targetID": "osenv",
      "size": 1
    },
    {
      "sourceID": "fstream-npm",
      "attributes": {},
      "targetID": "inherits",
      "size": 1
    },
    {
      "sourceID": "fstream-npm",
      "attributes": {},
      "targetID": "fstream-ignore",
      "size": 1
    },
    {
      "sourceID": "npmlog",
      "attributes": {},
      "targetID": "ansi",
      "size": 1
    },
    {
      "sourceID": "npm-registry-client",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "npm-registry-client",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "npm-registry-client",
      "attributes": {},
      "targetID": "semver",
      "size": 1
    },
    {
      "sourceID": "npm-registry-client",
      "attributes": {},
      "targetID": "slide",
      "size": 1
    },
    {
      "sourceID": "npm-registry-client",
      "attributes": {},
      "targetID": "graceful-fs",
      "size": 1
    },
    {
      "sourceID": "npm-registry-client",
      "attributes": {},
      "targetID": "rimraf",
      "size": 1
    },
    {
      "sourceID": "npm-registry-client",
      "attributes": {},
      "targetID": "npmlog",
      "size": 1
    },
    {
      "sourceID": "npm-registry-client",
      "attributes": {},
      "targetID": "retry",
      "size": 1
    },
    {
      "sourceID": "read-package-json",
      "attributes": {},
      "targetID": "graceful-fs",
      "size": 1
    },
    {
      "sourceID": "read-package-json",
      "attributes": {},
      "targetID": "lru-cache",
      "size": 1
    },
    {
      "sourceID": "read-package-json",
      "attributes": {},
      "targetID": "glob",
      "size": 1
    },
    {
      "sourceID": "glob",
      "attributes": {},
      "targetID": "graceful-fs",
      "size": 1
    },
    {
      "sourceID": "glob",
      "attributes": {},
      "targetID": "minimatch",
      "size": 1
    },
    {
      "sourceID": "glob",
      "attributes": {},
      "targetID": "inherits",
      "size": 1
    },
    {
      "sourceID": "npmconf",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "npmconf",
      "attributes": {},
      "targetID": "semver",
      "size": 1
    },
    {
      "sourceID": "npmconf",
      "attributes": {},
      "targetID": "ini",
      "size": 1
    },
    {
      "sourceID": "npmconf",
      "attributes": {},
      "targetID": "nopt",
      "size": 1
    },
    {
      "sourceID": "npmconf",
      "attributes": {},
      "targetID": "inherits",
      "size": 1
    },
    {
      "sourceID": "npmconf",
      "attributes": {},
      "targetID": "osenv",
      "size": 1
    },
    {
      "sourceID": "npmconf",
      "attributes": {},
      "targetID": "once",
      "size": 1
    },
    {
      "sourceID": "findup-sync",
      "attributes": {},
      "targetID": "lodash",
      "size": 1
    },
    {
      "sourceID": "findup-sync",
      "attributes": {},
      "targetID": "glob",
      "size": 1
    },
    {
      "sourceID": "node-minify",
      "attributes": {},
      "targetID": "uglify-js",
      "size": 1
    },
    {
      "sourceID": "node-minify",
      "attributes": {},
      "targetID": "sqwish",
      "size": 1
    },
    {
      "sourceID": "bal-util",
      "attributes": {},
      "targetID": "extendr",
      "size": 1
    },
    {
      "sourceID": "bal-util",
      "attributes": {},
      "targetID": "taskgroup",
      "size": 1
    },
    {
      "sourceID": "bal-util",
      "attributes": {},
      "targetID": "typechecker",
      "size": 1
    },
    {
      "sourceID": "extendr",
      "attributes": {},
      "targetID": "typechecker",
      "size": 1
    },
    {
      "sourceID": "taskgroup",
      "attributes": {},
      "targetID": "eventemitter2",
      "size": 1
    },
    {
      "sourceID": "underscorem",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "hubot",
      "attributes": {},
      "targetID": "express",
      "size": 1
    },
    {
      "sourceID": "hubot",
      "attributes": {},
      "targetID": "coffee-script",
      "size": 1
    },
    {
      "sourceID": "hubot",
      "attributes": {},
      "targetID": "optparse",
      "size": 1
    },
    {
      "sourceID": "hubot",
      "attributes": {},
      "targetID": "log",
      "size": 1
    },
    {
      "sourceID": "ndarray-ops",
      "attributes": {},
      "targetID": "ndarray",
      "size": 1
    },
    {
      "sourceID": "ndarray-ops",
      "attributes": {},
      "targetID": "cwise",
      "size": 1
    },
    {
      "sourceID": "typedarray-pool",
      "attributes": {},
      "targetID": "bit-twiddle",
      "size": 1
    },
    {
      "sourceID": "jade",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "jade",
      "attributes": {},
      "targetID": "commander",
      "size": 1
    },
    {
      "sourceID": "nodemailer",
      "attributes": {},
      "targetID": "simplesmtp",
      "size": 1
    },
    {
      "sourceID": "eco",
      "attributes": {},
      "targetID": "coffee-script",
      "size": 1
    },
    {
      "sourceID": "filed",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "flatiron",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "flatiron",
      "attributes": {},
      "targetID": "prompt",
      "size": 1
    },
    {
      "sourceID": "flatiron",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "flatiron",
      "attributes": {},
      "targetID": "director",
      "size": 1
    },
    {
      "sourceID": "flatiron",
      "attributes": {},
      "targetID": "broadway",
      "size": 1
    },
    {
      "sourceID": "winston",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "winston",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "winston",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "winston",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "winston",
      "attributes": {},
      "targetID": "stack-trace",
      "size": 1
    },
    {
      "sourceID": "winston",
      "attributes": {},
      "targetID": "eyes",
      "size": 1
    },
    {
      "sourceID": "winston",
      "attributes": {},
      "targetID": "cycle",
      "size": 1
    },
    {
      "sourceID": "coffeekup",
      "attributes": {},
      "targetID": "coffee-script",
      "size": 1
    },
    {
      "sourceID": "stylus",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "stylus",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "stylus",
      "attributes": {},
      "targetID": "cssom",
      "size": 1
    },
    {
      "sourceID": "xml2json",
      "attributes": {},
      "targetID": "node-expat",
      "size": 1
    },
    {
      "sourceID": "nano",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "nano",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "nano",
      "attributes": {},
      "targetID": "errs",
      "size": 1
    },
    {
      "sourceID": "nano",
      "attributes": {},
      "targetID": "follow",
      "size": 1
    },
    {
      "sourceID": "less",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "less",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "less",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "less",
      "attributes": {},
      "targetID": "ycssmin",
      "size": 1
    },
    {
      "sourceID": "uglify-js",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "uglify-js",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "uglify-js",
      "attributes": {},
      "targetID": "source-map",
      "size": 1
    },
    {
      "sourceID": "clean-css",
      "attributes": {},
      "targetID": "commander",
      "size": 1
    },
    {
      "sourceID": "datetime",
      "attributes": {},
      "targetID": "vows",
      "size": 1
    },
    {
      "sourceID": "vows",
      "attributes": {},
      "targetID": "eyes",
      "size": 1
    },
    {
      "sourceID": "vows",
      "attributes": {},
      "targetID": "diff",
      "size": 1
    },
    {
      "sourceID": "docco",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "docco",
      "attributes": {},
      "targetID": "commander",
      "size": 1
    },
    {
      "sourceID": "docco",
      "attributes": {},
      "targetID": "marked",
      "size": 1
    },
    {
      "sourceID": "docco",
      "attributes": {},
      "targetID": "highlight.js",
      "size": 1
    },
    {
      "sourceID": "xml2js",
      "attributes": {},
      "targetID": "sax",
      "size": 1
    },
    {
      "sourceID": "libxmljs",
      "attributes": {},
      "targetID": "bindings",
      "size": 1
    },
    {
      "sourceID": "handlebars",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "handlebars",
      "attributes": {},
      "targetID": "uglify-js",
      "size": 1
    },
    {
      "sourceID": "tap",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "tap",
      "attributes": {},
      "targetID": "slide",
      "size": 1
    },
    {
      "sourceID": "tap",
      "attributes": {},
      "targetID": "nopt",
      "size": 1
    },
    {
      "sourceID": "tap",
      "attributes": {},
      "targetID": "inherits",
      "size": 1
    },
    {
      "sourceID": "tap",
      "attributes": {},
      "targetID": "glob",
      "size": 1
    },
    {
      "sourceID": "tap",
      "attributes": {},
      "targetID": "deep-equal",
      "size": 1
    },
    {
      "sourceID": "tap",
      "attributes": {},
      "targetID": "difflet",
      "size": 1
    },
    {
      "sourceID": "tap",
      "attributes": {},
      "targetID": "yamlish",
      "size": 1
    },
    {
      "sourceID": "walk",
      "attributes": {},
      "targetID": "forEachAsync",
      "size": 1
    },
    {
      "sourceID": "split",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "memcached",
      "attributes": {},
      "targetID": "hashring",
      "size": 1
    },
    {
      "sourceID": "express-resource",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "express-resource",
      "attributes": {},
      "targetID": "lingo",
      "size": 1
    },
    {
      "sourceID": "express-resource",
      "attributes": {},
      "targetID": "methods",
      "size": 1
    },
    {
      "sourceID": "connect-assets",
      "attributes": {},
      "targetID": "snockets",
      "size": 1
    },
    {
      "sourceID": "knox",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "knox",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "knox",
      "attributes": {},
      "targetID": "xml2js",
      "size": 1
    },
    {
      "sourceID": "aws-sdk",
      "attributes": {},
      "targetID": "xml2js",
      "size": 1
    },
    {
      "sourceID": "aws-sdk",
      "attributes": {},
      "targetID": "xmlbuilder",
      "size": 1
    },
    {
      "sourceID": "fs-extra",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "fs-extra",
      "attributes": {},
      "targetID": "rimraf",
      "size": 1
    },
    {
      "sourceID": "fs-extra",
      "attributes": {},
      "targetID": "ncp",
      "size": 1
    },
    {
      "sourceID": "awssum",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "awssum",
      "attributes": {},
      "targetID": "xml2js",
      "size": 1
    },
    {
      "sourceID": "cradle",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "cradle",
      "attributes": {},
      "targetID": "follow",
      "size": 1
    },
    {
      "sourceID": "cli-color",
      "attributes": {},
      "targetID": "es5-ext",
      "size": 1
    },
    {
      "sourceID": "hashish",
      "attributes": {},
      "targetID": "traverse",
      "size": 1
    },
    {
      "sourceID": "htmlparser2",
      "attributes": {},
      "targetID": "readable-stream",
      "size": 1
    },
    {
      "sourceID": "netmask",
      "attributes": {},
      "targetID": "coffee-script",
      "size": 1
    },
    {
      "sourceID": "pkgcloud",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "pkgcloud",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "pkgcloud",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "pkgcloud",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "pkgcloud",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "pkgcloud",
      "attributes": {},
      "targetID": "filed",
      "size": 1
    },
    {
      "sourceID": "pkgcloud",
      "attributes": {},
      "targetID": "xml2js",
      "size": 1
    },
    {
      "sourceID": "pkgcloud",
      "attributes": {},
      "targetID": "errs",
      "size": 1
    },
    {
      "sourceID": "pkgcloud",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "pkgcloud",
      "attributes": {},
      "targetID": "eventemitter2",
      "size": 1
    },
    {
      "sourceID": "pkgcloud",
      "attributes": {},
      "targetID": "qs",
      "size": 1
    },
    {
      "sourceID": "pkgcloud",
      "attributes": {},
      "targetID": "utile",
      "size": 1
    },
    {
      "sourceID": "pkgcloud",
      "attributes": {},
      "targetID": "ip",
      "size": 1
    },
    {
      "sourceID": "mailparser",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "mailparser",
      "attributes": {},
      "targetID": "iconv",
      "size": 1
    },
    {
      "sourceID": "portfinder",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "forever-monitor",
      "attributes": {},
      "targetID": "minimatch",
      "size": 1
    },
    {
      "sourceID": "forever-monitor",
      "attributes": {},
      "targetID": "watch",
      "size": 1
    },
    {
      "sourceID": "forever-monitor",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "forever-monitor",
      "attributes": {},
      "targetID": "utile",
      "size": 1
    },
    {
      "sourceID": "forever-monitor",
      "attributes": {},
      "targetID": "broadway",
      "size": 1
    },
    {
      "sourceID": "passport",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "passport",
      "attributes": {},
      "targetID": "pause",
      "size": 1
    },
    {
      "sourceID": "jshint",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "jshint",
      "attributes": {},
      "targetID": "minimatch",
      "size": 1
    },
    {
      "sourceID": "jshint",
      "attributes": {},
      "targetID": "cli",
      "size": 1
    },
    {
      "sourceID": "jshint",
      "attributes": {},
      "targetID": "shelljs",
      "size": 1
    },
    {
      "sourceID": "nib",
      "attributes": {},
      "targetID": "stylus",
      "size": 1
    },
    {
      "sourceID": "grunt-contrib-stylus",
      "attributes": {},
      "targetID": "stylus",
      "size": 1
    },
    {
      "sourceID": "grunt-contrib-stylus",
      "attributes": {},
      "targetID": "nib",
      "size": 1
    },
    {
      "sourceID": "phantom",
      "attributes": {},
      "targetID": "dnode",
      "size": 1
    },
    {
      "sourceID": "phantom",
      "attributes": {},
      "targetID": "shoe",
      "size": 1
    },
    {
      "sourceID": "jslint",
      "attributes": {},
      "targetID": "nopt",
      "size": 1
    },
    {
      "sourceID": "bufferstream",
      "attributes": {},
      "targetID": "buffertools",
      "size": 1
    },
    {
      "sourceID": "browserify",
      "attributes": {},
      "targetID": "event-stream",
      "size": 1
    },
    {
      "sourceID": "browserify",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "browserify",
      "attributes": {},
      "targetID": "inherits",
      "size": 1
    },
    {
      "sourceID": "browserify",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "browserify",
      "attributes": {},
      "targetID": "duplexer",
      "size": 1
    },
    {
      "sourceID": "browserify",
      "attributes": {},
      "targetID": "shell-quote",
      "size": 1
    },
    {
      "sourceID": "browserify",
      "attributes": {},
      "targetID": "concat-stream",
      "size": 1
    },
    {
      "sourceID": "browserify",
      "attributes": {},
      "targetID": "JSONStream",
      "size": 1
    },
    {
      "sourceID": "nodeunit",
      "attributes": {},
      "targetID": "tap",
      "size": 1
    },
    {
      "sourceID": "vine",
      "attributes": {},
      "targetID": "outcome",
      "size": 1
    },
    {
      "sourceID": "findit",
      "attributes": {},
      "targetID": "seq",
      "size": 1
    },
    {
      "sourceID": "plugin",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "plugin",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "plugin",
      "attributes": {},
      "targetID": "structr",
      "size": 1
    },
    {
      "sourceID": "plugin",
      "attributes": {},
      "targetID": "step",
      "size": 1
    },
    {
      "sourceID": "plugin",
      "attributes": {},
      "targetID": "outcome",
      "size": 1
    },
    {
      "sourceID": "plugin",
      "attributes": {},
      "targetID": "dref",
      "size": 1
    },
    {
      "sourceID": "plugin",
      "attributes": {},
      "targetID": "toarray",
      "size": 1
    },
    {
      "sourceID": "plugin",
      "attributes": {},
      "targetID": "sift",
      "size": 1
    },
    {
      "sourceID": "plugin",
      "attributes": {},
      "targetID": "resolve",
      "size": 1
    },
    {
      "sourceID": "sk",
      "attributes": {},
      "targetID": "dateformat",
      "size": 1
    },
    {
      "sourceID": "sk",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "sk",
      "attributes": {},
      "targetID": "structr",
      "size": 1
    },
    {
      "sourceID": "sk",
      "attributes": {},
      "targetID": "htmlparser",
      "size": 1
    },
    {
      "sourceID": "sk",
      "attributes": {},
      "targetID": "printf",
      "size": 1
    },
    {
      "sourceID": "stitch",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "stitch",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "jasmine-node",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "jasmine-node",
      "attributes": {},
      "targetID": "requirejs",
      "size": 1
    },
    {
      "sourceID": "jasmine-node",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "jasmine-node",
      "attributes": {},
      "targetID": "coffee-script",
      "size": 1
    },
    {
      "sourceID": "jasmine-node",
      "attributes": {},
      "targetID": "gaze",
      "size": 1
    },
    {
      "sourceID": "jasmine-node",
      "attributes": {},
      "targetID": "walkdir",
      "size": 1
    },
    {
      "sourceID": "jsdom",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "jsdom",
      "attributes": {},
      "targetID": "htmlparser2",
      "size": 1
    },
    {
      "sourceID": "jsdom",
      "attributes": {},
      "targetID": "cssom",
      "size": 1
    },
    {
      "sourceID": "jsdom",
      "attributes": {},
      "targetID": "contextify",
      "size": 1
    },
    {
      "sourceID": "superagent",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "superagent",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "superagent",
      "attributes": {},
      "targetID": "emitter-component",
      "size": 1
    },
    {
      "sourceID": "superagent",
      "attributes": {},
      "targetID": "qs",
      "size": 1
    },
    {
      "sourceID": "superagent",
      "attributes": {},
      "targetID": "formidable",
      "size": 1
    },
    {
      "sourceID": "superagent",
      "attributes": {},
      "targetID": "methods",
      "size": 1
    },
    {
      "sourceID": "superagent",
      "attributes": {},
      "targetID": "cookiejar",
      "size": 1
    },
    {
      "sourceID": "readdirp",
      "attributes": {},
      "targetID": "graceful-fs",
      "size": 1
    },
    {
      "sourceID": "readdirp",
      "attributes": {},
      "targetID": "minimatch",
      "size": 1
    },
    {
      "sourceID": "ws",
      "attributes": {},
      "targetID": "commander",
      "size": 1
    },
    {
      "sourceID": "node-xmpp",
      "attributes": {},
      "targetID": "faye-websocket",
      "size": 1
    },
    {
      "sourceID": "node-xmpp",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "node-xmpp",
      "attributes": {},
      "targetID": "mocha",
      "size": 1
    },
    {
      "sourceID": "node-xmpp",
      "attributes": {},
      "targetID": "browserify",
      "size": 1
    },
    {
      "sourceID": "node-xmpp",
      "attributes": {},
      "targetID": "node-expat",
      "size": 1
    },
    {
      "sourceID": "node-xmpp",
      "attributes": {},
      "targetID": "ltx",
      "size": 1
    },
    {
      "sourceID": "watchr",
      "attributes": {},
      "targetID": "bal-util",
      "size": 1
    },
    {
      "sourceID": "watchr",
      "attributes": {},
      "targetID": "extendr",
      "size": 1
    },
    {
      "sourceID": "watchr",
      "attributes": {},
      "targetID": "taskgroup",
      "size": 1
    },
    {
      "sourceID": "watchr",
      "attributes": {},
      "targetID": "typechecker",
      "size": 1
    },
    {
      "sourceID": "celeri",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "celeri",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "celeri",
      "attributes": {},
      "targetID": "structr",
      "size": 1
    },
    {
      "sourceID": "celeri",
      "attributes": {},
      "targetID": "tq",
      "size": 1
    },
    {
      "sourceID": "celeri",
      "attributes": {},
      "targetID": "plugin",
      "size": 1
    },
    {
      "sourceID": "celeri",
      "attributes": {},
      "targetID": "crema",
      "size": 1
    },
    {
      "sourceID": "celeri",
      "attributes": {},
      "targetID": "outcome",
      "size": 1
    },
    {
      "sourceID": "celeri",
      "attributes": {},
      "targetID": "keypress",
      "size": 1
    },
    {
      "sourceID": "coa",
      "attributes": {},
      "targetID": "q",
      "size": 1
    },
    {
      "sourceID": "ometajs",
      "attributes": {},
      "targetID": "q",
      "size": 1
    },
    {
      "sourceID": "ometajs",
      "attributes": {},
      "targetID": "uglify-js",
      "size": 1
    },
    {
      "sourceID": "ometajs",
      "attributes": {},
      "targetID": "coa",
      "size": 1
    },
    {
      "sourceID": "q-fs",
      "attributes": {},
      "targetID": "q",
      "size": 1
    },
    {
      "sourceID": "q-fs",
      "attributes": {},
      "targetID": "q-io",
      "size": 1
    },
    {
      "sourceID": "falafel",
      "attributes": {},
      "targetID": "esprima",
      "size": 1
    },
    {
      "sourceID": "cli-table",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "cli",
      "attributes": {},
      "targetID": "glob",
      "size": 1
    },
    {
      "sourceID": "bunyan",
      "attributes": {},
      "targetID": "dtrace-provider",
      "size": 1
    },
    {
      "sourceID": "utile",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "utile",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "utile",
      "attributes": {},
      "targetID": "rimraf",
      "size": 1
    },
    {
      "sourceID": "utile",
      "attributes": {},
      "targetID": "deep-equal",
      "size": 1
    },
    {
      "sourceID": "utile",
      "attributes": {},
      "targetID": "ncp",
      "size": 1
    },
    {
      "sourceID": "utile",
      "attributes": {},
      "targetID": "i",
      "size": 1
    },
    {
      "sourceID": "send",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "send",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "send",
      "attributes": {},
      "targetID": "fresh",
      "size": 1
    },
    {
      "sourceID": "jison",
      "attributes": {},
      "targetID": "esprima",
      "size": 1
    },
    {
      "sourceID": "jison",
      "attributes": {},
      "targetID": "nomnom",
      "size": 1
    },
    {
      "sourceID": "jison",
      "attributes": {},
      "targetID": "escodegen",
      "size": 1
    },
    {
      "sourceID": "jison",
      "attributes": {},
      "targetID": "cjson",
      "size": 1
    },
    {
      "sourceID": "jison",
      "attributes": {},
      "targetID": "JSONSelect",
      "size": 1
    },
    {
      "sourceID": "socket.io-client",
      "attributes": {},
      "targetID": "uglify-js",
      "size": 1
    },
    {
      "sourceID": "socket.io-client",
      "attributes": {},
      "targetID": "ws",
      "size": 1
    },
    {
      "sourceID": "socket.io-client",
      "attributes": {},
      "targetID": "xmlhttprequest",
      "size": 1
    },
    {
      "sourceID": "resource",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "resource",
      "attributes": {},
      "targetID": "which",
      "size": 1
    },
    {
      "sourceID": "resource",
      "attributes": {},
      "targetID": "eventemitter2",
      "size": 1
    },
    {
      "sourceID": "jake",
      "attributes": {},
      "targetID": "minimatch",
      "size": 1
    },
    {
      "sourceID": "jake",
      "attributes": {},
      "targetID": "utilities",
      "size": 1
    },
    {
      "sourceID": "assert",
      "attributes": {},
      "targetID": "util",
      "size": 1
    },
    {
      "sourceID": "detective",
      "attributes": {},
      "targetID": "esprima",
      "size": 1
    },
    {
      "sourceID": "detective",
      "attributes": {},
      "targetID": "escodegen",
      "size": 1
    },
    {
      "sourceID": "istanbul",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "istanbul",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "istanbul",
      "attributes": {},
      "targetID": "abbrev",
      "size": 1
    },
    {
      "sourceID": "istanbul",
      "attributes": {},
      "targetID": "nopt",
      "size": 1
    },
    {
      "sourceID": "istanbul",
      "attributes": {},
      "targetID": "which",
      "size": 1
    },
    {
      "sourceID": "istanbul",
      "attributes": {},
      "targetID": "handlebars",
      "size": 1
    },
    {
      "sourceID": "istanbul",
      "attributes": {},
      "targetID": "esprima",
      "size": 1
    },
    {
      "sourceID": "istanbul",
      "attributes": {},
      "targetID": "resolve",
      "size": 1
    },
    {
      "sourceID": "istanbul",
      "attributes": {},
      "targetID": "escodegen",
      "size": 1
    },
    {
      "sourceID": "istanbul",
      "attributes": {},
      "targetID": "wordwrap",
      "size": 1
    },
    {
      "sourceID": "tiny-lr",
      "attributes": {},
      "targetID": "faye-websocket",
      "size": 1
    },
    {
      "sourceID": "tiny-lr",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "tiny-lr",
      "attributes": {},
      "targetID": "qs",
      "size": 1
    },
    {
      "sourceID": "argparse",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "argparse",
      "attributes": {},
      "targetID": "underscore.string",
      "size": 1
    },
    {
      "sourceID": "dref",
      "attributes": {},
      "targetID": "structr",
      "size": 1
    },
    {
      "sourceID": "dref",
      "attributes": {},
      "targetID": "dref",
      "size": 1
    },
    {
      "sourceID": "dref",
      "attributes": {},
      "targetID": "type-component",
      "size": 1
    },
    {
      "sourceID": "haml-coffee",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "haml-coffee",
      "attributes": {},
      "targetID": "coffee-script",
      "size": 1
    },
    {
      "sourceID": "haml-coffee",
      "attributes": {},
      "targetID": "walkdir",
      "size": 1
    },
    {
      "sourceID": "binary",
      "attributes": {},
      "targetID": "buffers",
      "size": 1
    },
    {
      "sourceID": "forever",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "forever",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "forever",
      "attributes": {},
      "targetID": "watch",
      "size": 1
    },
    {
      "sourceID": "forever",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "forever",
      "attributes": {},
      "targetID": "flatiron",
      "size": 1
    },
    {
      "sourceID": "forever",
      "attributes": {},
      "targetID": "winston",
      "size": 1
    },
    {
      "sourceID": "forever",
      "attributes": {},
      "targetID": "forever-monitor",
      "size": 1
    },
    {
      "sourceID": "forever",
      "attributes": {},
      "targetID": "utile",
      "size": 1
    },
    {
      "sourceID": "forever",
      "attributes": {},
      "targetID": "nconf",
      "size": 1
    },
    {
      "sourceID": "forever",
      "attributes": {},
      "targetID": "cliff",
      "size": 1
    },
    {
      "sourceID": "forever",
      "attributes": {},
      "targetID": "nssocket",
      "size": 1
    },
    {
      "sourceID": "serialport",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "serialport",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "serialport",
      "attributes": {},
      "targetID": "bindings",
      "size": 1
    },
    {
      "sourceID": "serialport",
      "attributes": {},
      "targetID": "sf",
      "size": 1
    },
    {
      "sourceID": "connect-redis",
      "attributes": {},
      "targetID": "redis",
      "size": 1
    },
    {
      "sourceID": "connect-redis",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "dnode",
      "attributes": {},
      "targetID": "jsonify",
      "size": 1
    },
    {
      "sourceID": "union",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "union",
      "attributes": {},
      "targetID": "qs",
      "size": 1
    },
    {
      "sourceID": "passport-local",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "passport-local",
      "attributes": {},
      "targetID": "passport",
      "size": 1
    },
    {
      "sourceID": "markdown",
      "attributes": {},
      "targetID": "nopt",
      "size": 1
    },
    {
      "sourceID": "microtime",
      "attributes": {},
      "targetID": "bindings",
      "size": 1
    },
    {
      "sourceID": "rss",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "rss",
      "attributes": {},
      "targetID": "xml",
      "size": 1
    },
    {
      "sourceID": "connect-mongodb",
      "attributes": {},
      "targetID": "connect",
      "size": 1
    },
    {
      "sourceID": "connect-mongodb",
      "attributes": {},
      "targetID": "mongodb",
      "size": 1
    },
    {
      "sourceID": "connect-form",
      "attributes": {},
      "targetID": "formidable",
      "size": 1
    },
    {
      "sourceID": "zombie",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "zombie",
      "attributes": {},
      "targetID": "q",
      "size": 1
    },
    {
      "sourceID": "zombie",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "zombie",
      "attributes": {},
      "targetID": "jsdom",
      "size": 1
    },
    {
      "sourceID": "zombie",
      "attributes": {},
      "targetID": "ws",
      "size": 1
    },
    {
      "sourceID": "zombie",
      "attributes": {},
      "targetID": "ms",
      "size": 1
    },
    {
      "sourceID": "jugglingdb",
      "attributes": {},
      "targetID": "inflection",
      "size": 1
    },
    {
      "sourceID": "hiredis",
      "attributes": {},
      "targetID": "bindings",
      "size": 1
    },
    {
      "sourceID": "swig",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "node-static",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "node-static",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "node-static",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "bootstrap",
      "attributes": {},
      "targetID": "commander",
      "size": 1
    },
    {
      "sourceID": "nconf",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "nconf",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "nconf",
      "attributes": {},
      "targetID": "ini",
      "size": 1
    },
    {
      "sourceID": "nconf",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "seq",
      "attributes": {},
      "targetID": "hashish",
      "size": 1
    },
    {
      "sourceID": "azure",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "azure",
      "attributes": {},
      "targetID": "dateformat",
      "size": 1
    },
    {
      "sourceID": "azure",
      "attributes": {},
      "targetID": "node-uuid",
      "size": 1
    },
    {
      "sourceID": "azure",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "azure",
      "attributes": {},
      "targetID": "validator",
      "size": 1
    },
    {
      "sourceID": "azure",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "azure",
      "attributes": {},
      "targetID": "xml2js",
      "size": 1
    },
    {
      "sourceID": "azure",
      "attributes": {},
      "targetID": "xmlbuilder",
      "size": 1
    },
    {
      "sourceID": "azure",
      "attributes": {},
      "targetID": "tunnel",
      "size": 1
    },
    {
      "sourceID": "pg",
      "attributes": {},
      "targetID": "generic-pool",
      "size": 1
    },
    {
      "sourceID": "pg",
      "attributes": {},
      "targetID": "ref",
      "size": 1
    },
    {
      "sourceID": "jqtpl",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "semver",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "ini",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "slide",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "abbrev",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "graceful-fs",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "minimatch",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "nopt",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "rimraf",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "which",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "tar",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "fstream",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "inherits",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "read",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "lru-cache",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "node-gyp",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "fstream-npm",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "archy",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "npmlog",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "ansi",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "npm-registry-client",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "read-package-json",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "glob",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "osenv",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "retry",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "once",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "npmconf",
      "size": 1
    },
    {
      "sourceID": "npm",
      "attributes": {},
      "targetID": "opener",
      "size": 1
    },
    {
      "sourceID": "nomnom",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "nomnom",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "passport-oauth",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "passport-oauth",
      "attributes": {},
      "targetID": "passport",
      "size": 1
    },
    {
      "sourceID": "passport-oauth",
      "attributes": {},
      "targetID": "oauth",
      "size": 1
    },
    {
      "sourceID": "passport-twitter",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "passport-twitter",
      "attributes": {},
      "targetID": "passport-oauth",
      "size": 1
    },
    {
      "sourceID": "mongoskin",
      "attributes": {},
      "targetID": "mongodb",
      "size": 1
    },
    {
      "sourceID": "emailjs",
      "attributes": {},
      "targetID": "moment",
      "size": 1
    },
    {
      "sourceID": "emailjs",
      "attributes": {},
      "targetID": "bufferjs",
      "size": 1
    },
    {
      "sourceID": "connect-mongo",
      "attributes": {},
      "targetID": "mongodb",
      "size": 1
    },
    {
      "sourceID": "bcrypt",
      "attributes": {},
      "targetID": "bindings",
      "size": 1
    },
    {
      "sourceID": "ntwitter",
      "attributes": {},
      "targetID": "cookies",
      "size": 1
    },
    {
      "sourceID": "ntwitter",
      "attributes": {},
      "targetID": "oauth",
      "size": 1
    },
    {
      "sourceID": "ntwitter",
      "attributes": {},
      "targetID": "keygrip",
      "size": 1
    },
    {
      "sourceID": "juice",
      "attributes": {},
      "targetID": "commander",
      "size": 1
    },
    {
      "sourceID": "juice",
      "attributes": {},
      "targetID": "batch",
      "size": 1
    },
    {
      "sourceID": "juice",
      "attributes": {},
      "targetID": "cssom",
      "size": 1
    },
    {
      "sourceID": "juice",
      "attributes": {},
      "targetID": "jsdom",
      "size": 1
    },
    {
      "sourceID": "juice",
      "attributes": {},
      "targetID": "superagent",
      "size": 1
    },
    {
      "sourceID": "pause-stream",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "sequelize",
      "attributes": {},
      "targetID": "lodash",
      "size": 1
    },
    {
      "sourceID": "sequelize",
      "attributes": {},
      "targetID": "underscore.string",
      "size": 1
    },
    {
      "sourceID": "sequelize",
      "attributes": {},
      "targetID": "commander",
      "size": 1
    },
    {
      "sourceID": "sequelize",
      "attributes": {},
      "targetID": "validator",
      "size": 1
    },
    {
      "sourceID": "sequelize",
      "attributes": {},
      "targetID": "lingo",
      "size": 1
    },
    {
      "sourceID": "sequelize",
      "attributes": {},
      "targetID": "moment",
      "size": 1
    },
    {
      "sourceID": "sequelize",
      "attributes": {},
      "targetID": "generic-pool",
      "size": 1
    },
    {
      "sourceID": "sequelize",
      "attributes": {},
      "targetID": "promise",
      "size": 1
    },
    {
      "sourceID": "tar.gz",
      "attributes": {},
      "targetID": "commander",
      "size": 1
    },
    {
      "sourceID": "tar.gz",
      "attributes": {},
      "targetID": "tar",
      "size": 1
    },
    {
      "sourceID": "tar.gz",
      "attributes": {},
      "targetID": "fstream",
      "size": 1
    },
    {
      "sourceID": "prettyjson",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "escodegen",
      "attributes": {},
      "targetID": "estraverse",
      "size": 1
    },
    {
      "sourceID": "escodegen",
      "attributes": {},
      "targetID": "esprima",
      "size": 1
    },
    {
      "sourceID": "escodegen",
      "attributes": {},
      "targetID": "source-map",
      "size": 1
    },
    {
      "sourceID": "url",
      "attributes": {},
      "targetID": "querystring",
      "size": 1
    },
    {
      "sourceID": "ltx",
      "attributes": {},
      "targetID": "sax",
      "size": 1
    },
    {
      "sourceID": "ltx",
      "attributes": {},
      "targetID": "node-expat",
      "size": 1
    },
    {
      "sourceID": "bouncy",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "bouncy",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "simplicial-complex",
      "attributes": {},
      "targetID": "bit-twiddle",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "lodash",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "hogan.js",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "semver",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "abbrev",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "nopt",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "rimraf",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "which",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "tar",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "fstream",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "archy",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "read-package-json",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "glob",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "tmp",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "rc",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "unzip",
      "size": 1
    },
    {
      "sourceID": "bower",
      "attributes": {},
      "targetID": "update-notifier",
      "size": 1
    },
    {
      "sourceID": "rc",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "rc",
      "attributes": {},
      "targetID": "ini",
      "size": 1
    },
    {
      "sourceID": "rc",
      "attributes": {},
      "targetID": "deep-extend",
      "size": 1
    },
    {
      "sourceID": "unzip",
      "attributes": {},
      "targetID": "fstream",
      "size": 1
    },
    {
      "sourceID": "unzip",
      "attributes": {},
      "targetID": "readable-stream",
      "size": 1
    },
    {
      "sourceID": "unzip",
      "attributes": {},
      "targetID": "binary",
      "size": 1
    },
    {
      "sourceID": "unzip",
      "attributes": {},
      "targetID": "setimmediate",
      "size": 1
    },
    {
      "sourceID": "scaffolder",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "scaffolder",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "scaffolder",
      "attributes": {},
      "targetID": "underscore.string",
      "size": 1
    },
    {
      "sourceID": "scaffolder",
      "attributes": {},
      "targetID": "nopt",
      "size": 1
    },
    {
      "sourceID": "scaffolder",
      "attributes": {},
      "targetID": "read",
      "size": 1
    },
    {
      "sourceID": "scaffolder",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "scaffolder",
      "attributes": {},
      "targetID": "out",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "socket.io",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "semver",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "prompt",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "winston",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "eventemitter2",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "portfinder",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "socket.io-client",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "union",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "nconf",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "npm",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "traverse",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "ecstatic",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "lazy",
      "size": 1
    },
    {
      "sourceID": "hook.io",
      "attributes": {},
      "targetID": "jsonify",
      "size": 1
    },
    {
      "sourceID": "fs.extra",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "fs.extra",
      "attributes": {},
      "targetID": "walk",
      "size": 1
    },
    {
      "sourceID": "fs.extra",
      "attributes": {},
      "targetID": "fs-extra",
      "size": 1
    },
    {
      "sourceID": "now",
      "attributes": {},
      "targetID": "socket.io",
      "size": 1
    },
    {
      "sourceID": "now",
      "attributes": {},
      "targetID": "node-proxy",
      "size": 1
    },
    {
      "sourceID": "brfs",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "brfs",
      "attributes": {},
      "targetID": "falafel",
      "size": 1
    },
    {
      "sourceID": "brfs",
      "attributes": {},
      "targetID": "escodegen",
      "size": 1
    },
    {
      "sourceID": "mongojs",
      "attributes": {},
      "targetID": "mongodb",
      "size": 1
    },
    {
      "sourceID": "mongojs",
      "attributes": {},
      "targetID": "readable-stream",
      "size": 1
    },
    {
      "sourceID": "feedparser",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "feedparser",
      "attributes": {},
      "targetID": "readable-stream",
      "size": 1
    },
    {
      "sourceID": "feedparser",
      "attributes": {},
      "targetID": "sax",
      "size": 1
    },
    {
      "sourceID": "broadway",
      "attributes": {},
      "targetID": "winston",
      "size": 1
    },
    {
      "sourceID": "broadway",
      "attributes": {},
      "targetID": "eventemitter2",
      "size": 1
    },
    {
      "sourceID": "broadway",
      "attributes": {},
      "targetID": "utile",
      "size": 1
    },
    {
      "sourceID": "broadway",
      "attributes": {},
      "targetID": "nconf",
      "size": 1
    },
    {
      "sourceID": "broadway",
      "attributes": {},
      "targetID": "cliff",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "node-uuid",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "backoff",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "semver",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "lru-cache",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "once",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "qs",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "bunyan",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "deep-equal",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "formidable",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "assert-plus",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "dtrace-provider",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "negotiator",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "verror",
      "size": 1
    },
    {
      "sourceID": "restify",
      "attributes": {},
      "targetID": "spdy",
      "size": 1
    },
    {
      "sourceID": "cliff",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "cliff",
      "attributes": {},
      "targetID": "winston",
      "size": 1
    },
    {
      "sourceID": "cliff",
      "attributes": {},
      "targetID": "eyes",
      "size": 1
    },
    {
      "sourceID": "JSONStream",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "plist",
      "attributes": {},
      "targetID": "xmldom",
      "size": 1
    },
    {
      "sourceID": "plist",
      "attributes": {},
      "targetID": "xmlbuilder",
      "size": 1
    },
    {
      "sourceID": "natural",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "natural",
      "attributes": {},
      "targetID": "sylvester",
      "size": 1
    },
    {
      "sourceID": "global",
      "attributes": {},
      "targetID": "process",
      "size": 1
    },
    {
      "sourceID": "ecstatic",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "ecstatic",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "ecstatic",
      "attributes": {},
      "targetID": "ent",
      "size": 1
    },
    {
      "sourceID": "useragent",
      "attributes": {},
      "targetID": "lru-cache",
      "size": 1
    },
    {
      "sourceID": "snockets",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "snockets",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "snockets",
      "attributes": {},
      "targetID": "coffee-script",
      "size": 1
    },
    {
      "sourceID": "snockets",
      "attributes": {},
      "targetID": "uglify-js",
      "size": 1
    },
    {
      "sourceID": "soupselect",
      "attributes": {},
      "targetID": "nodeunit",
      "size": 1
    },
    {
      "sourceID": "soupselect",
      "attributes": {},
      "targetID": "htmlparser",
      "size": 1
    },
    {
      "sourceID": "mailer",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "mailer",
      "attributes": {},
      "targetID": "nodemailer",
      "size": 1
    },
    {
      "sourceID": "archiver",
      "attributes": {},
      "targetID": "readable-stream",
      "size": 1
    },
    {
      "sourceID": "aws2js",
      "attributes": {},
      "targetID": "lodash",
      "size": 1
    },
    {
      "sourceID": "aws2js",
      "attributes": {},
      "targetID": "semver",
      "size": 1
    },
    {
      "sourceID": "aws2js",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "aws2js",
      "attributes": {},
      "targetID": "xml2js",
      "size": 1
    },
    {
      "sourceID": "websocket.io",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "websocket.io",
      "attributes": {},
      "targetID": "ws",
      "size": 1
    },
    {
      "sourceID": "reducers",
      "attributes": {},
      "targetID": "reducible",
      "size": 1
    },
    {
      "sourceID": "reducible",
      "attributes": {},
      "targetID": "method",
      "size": 1
    },
    {
      "sourceID": "coffee-script-redux",
      "attributes": {},
      "targetID": "escodegen",
      "size": 1
    },
    {
      "sourceID": "coffee-script-redux",
      "attributes": {},
      "targetID": "source-map",
      "size": 1
    },
    {
      "sourceID": "source-map",
      "attributes": {},
      "targetID": "amdefine",
      "size": 1
    },
    {
      "sourceID": "time",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "time",
      "attributes": {},
      "targetID": "bindings",
      "size": 1
    },
    {
      "sourceID": "cson",
      "attributes": {},
      "targetID": "coffee-script",
      "size": 1
    },
    {
      "sourceID": "cson",
      "attributes": {},
      "targetID": "js2coffee",
      "size": 1
    },
    {
      "sourceID": "resourceful",
      "attributes": {},
      "targetID": "node-uuid",
      "size": 1
    },
    {
      "sourceID": "resourceful",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "resourceful",
      "attributes": {},
      "targetID": "cradle",
      "size": 1
    },
    {
      "sourceID": "resourceful",
      "attributes": {},
      "targetID": "utile",
      "size": 1
    },
    {
      "sourceID": "resourceful",
      "attributes": {},
      "targetID": "i",
      "size": 1
    },
    {
      "sourceID": "resourceful",
      "attributes": {},
      "targetID": "revalidator",
      "size": 1
    },
    {
      "sourceID": "execSync",
      "attributes": {},
      "targetID": "ffi",
      "size": 1
    },
    {
      "sourceID": "loader-utils",
      "attributes": {},
      "targetID": "json5",
      "size": 1
    },
    {
      "sourceID": "wd",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "wd",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "wd",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "wd",
      "attributes": {},
      "targetID": "q",
      "size": 1
    },
    {
      "sourceID": "fs-watch-tree",
      "attributes": {},
      "targetID": "when",
      "size": 1
    },
    {
      "sourceID": "glob-whatev",
      "attributes": {},
      "targetID": "minimatch",
      "size": 1
    },
    {
      "sourceID": "hapi",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "hapi",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "hapi",
      "attributes": {},
      "targetID": "semver",
      "size": 1
    },
    {
      "sourceID": "hapi",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "hapi",
      "attributes": {},
      "targetID": "lru-cache",
      "size": 1
    },
    {
      "sourceID": "hapi",
      "attributes": {},
      "targetID": "hoek",
      "size": 1
    },
    {
      "sourceID": "hapi",
      "attributes": {},
      "targetID": "negotiator",
      "size": 1
    },
    {
      "sourceID": "coffeecup",
      "attributes": {},
      "targetID": "coffee-script",
      "size": 1
    },
    {
      "sourceID": "coffeecup",
      "attributes": {},
      "targetID": "stylus",
      "size": 1
    },
    {
      "sourceID": "coffeecup",
      "attributes": {},
      "targetID": "uglify-js",
      "size": 1
    },
    {
      "sourceID": "coffeecup",
      "attributes": {},
      "targetID": "optparse",
      "size": 1
    },
    {
      "sourceID": "js-yaml",
      "attributes": {},
      "targetID": "esprima",
      "size": 1
    },
    {
      "sourceID": "js-yaml",
      "attributes": {},
      "targetID": "argparse",
      "size": 1
    },
    {
      "sourceID": "jeesh",
      "attributes": {},
      "targetID": "bean",
      "size": 1
    },
    {
      "sourceID": "jeesh",
      "attributes": {},
      "targetID": "bonzo",
      "size": 1
    },
    {
      "sourceID": "jeesh",
      "attributes": {},
      "targetID": "qwery",
      "size": 1
    },
    {
      "sourceID": "jeesh",
      "attributes": {},
      "targetID": "domready",
      "size": 1
    },
    {
      "sourceID": "everyauth",
      "attributes": {},
      "targetID": "express",
      "size": 1
    },
    {
      "sourceID": "everyauth",
      "attributes": {},
      "targetID": "connect",
      "size": 1
    },
    {
      "sourceID": "everyauth",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "everyauth",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "everyauth",
      "attributes": {},
      "targetID": "xml2js",
      "size": 1
    },
    {
      "sourceID": "everyauth",
      "attributes": {},
      "targetID": "oauth",
      "size": 1
    },
    {
      "sourceID": "everyauth",
      "attributes": {},
      "targetID": "openid",
      "size": 1
    },
    {
      "sourceID": "deferred",
      "attributes": {},
      "targetID": "es5-ext",
      "size": 1
    },
    {
      "sourceID": "postal",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "ahr2",
      "attributes": {},
      "targetID": "bufferjs",
      "size": 1
    },
    {
      "sourceID": "ahr2",
      "attributes": {},
      "targetID": "future",
      "size": 1
    },
    {
      "sourceID": "source-map-support",
      "attributes": {},
      "targetID": "source-map",
      "size": 1
    },
    {
      "sourceID": "needle",
      "attributes": {},
      "targetID": "qs",
      "size": 1
    },
    {
      "sourceID": "needle",
      "attributes": {},
      "targetID": "iconv-lite",
      "size": 1
    },
    {
      "sourceID": "read-stream",
      "attributes": {},
      "targetID": "readable-stream",
      "size": 1
    },
    {
      "sourceID": "read-stream",
      "attributes": {},
      "targetID": "process",
      "size": 1
    },
    {
      "sourceID": "write-stream",
      "attributes": {},
      "targetID": "readable-stream",
      "size": 1
    },
    {
      "sourceID": "sockjs",
      "attributes": {},
      "targetID": "faye-websocket",
      "size": 1
    },
    {
      "sourceID": "sockjs",
      "attributes": {},
      "targetID": "node-uuid",
      "size": 1
    },
    {
      "sourceID": "engine.io",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "engine.io",
      "attributes": {},
      "targetID": "ws",
      "size": 1
    },
    {
      "sourceID": "crdt",
      "attributes": {},
      "targetID": "scuttlebutt",
      "size": 1
    },
    {
      "sourceID": "mux-demux",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "mux-demux",
      "attributes": {},
      "targetID": "xtend",
      "size": 1
    },
    {
      "sourceID": "mux-demux",
      "attributes": {},
      "targetID": "duplex",
      "size": 1
    },
    {
      "sourceID": "mux-demux",
      "attributes": {},
      "targetID": "stream-combiner",
      "size": 1
    },
    {
      "sourceID": "devnull",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "d3",
      "attributes": {},
      "targetID": "jsdom",
      "size": 1
    },
    {
      "sourceID": "twitter",
      "attributes": {},
      "targetID": "cookies",
      "size": 1
    },
    {
      "sourceID": "twitter",
      "attributes": {},
      "targetID": "oauth",
      "size": 1
    },
    {
      "sourceID": "twitter",
      "attributes": {},
      "targetID": "keygrip",
      "size": 1
    },
    {
      "sourceID": "less-middleware",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "less-middleware",
      "attributes": {},
      "targetID": "less",
      "size": 1
    },
    {
      "sourceID": "i18n",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "i18n",
      "attributes": {},
      "targetID": "sprintf",
      "size": 1
    },
    {
      "sourceID": "pushover",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "pushover",
      "attributes": {},
      "targetID": "inherits",
      "size": 1
    },
    {
      "sourceID": "pushover",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "fs-tools",
      "attributes": {},
      "targetID": "lodash",
      "size": 1
    },
    {
      "sourceID": "fs-tools",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "hbs",
      "attributes": {},
      "targetID": "handlebars",
      "size": 1
    },
    {
      "sourceID": "hbs",
      "attributes": {},
      "targetID": "after",
      "size": 1
    },
    {
      "sourceID": "follow",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "phantomjs",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "phantomjs",
      "attributes": {},
      "targetID": "rimraf",
      "size": 1
    },
    {
      "sourceID": "phantomjs",
      "attributes": {},
      "targetID": "npmconf",
      "size": 1
    },
    {
      "sourceID": "phantomjs",
      "attributes": {},
      "targetID": "adm-zip",
      "size": 1
    },
    {
      "sourceID": "phantomjs",
      "attributes": {},
      "targetID": "ncp",
      "size": 1
    },
    {
      "sourceID": "phantomjs",
      "attributes": {},
      "targetID": "kew",
      "size": 1
    },
    {
      "sourceID": "tracer",
      "attributes": {},
      "targetID": "dateformat",
      "size": 1
    },
    {
      "sourceID": "tracer",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "axon",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "nssocket",
      "attributes": {},
      "targetID": "eventemitter2",
      "size": 1
    },
    {
      "sourceID": "nssocket",
      "attributes": {},
      "targetID": "lazy",
      "size": 1
    },
    {
      "sourceID": "dropbox",
      "attributes": {},
      "targetID": "open",
      "size": 1
    },
    {
      "sourceID": "cluster",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "cluster",
      "attributes": {},
      "targetID": "log",
      "size": 1
    },
    {
      "sourceID": "aws-lib",
      "attributes": {},
      "targetID": "sax",
      "size": 1
    },
    {
      "sourceID": "aws-lib",
      "attributes": {},
      "targetID": "xml2js",
      "size": 1
    },
    {
      "sourceID": "node-phantom",
      "attributes": {},
      "targetID": "socket.io",
      "size": 1
    },
    {
      "sourceID": "gzippo",
      "attributes": {},
      "targetID": "send",
      "size": 1
    },
    {
      "sourceID": "verror",
      "attributes": {},
      "targetID": "extsprintf",
      "size": 1
    },
    {
      "sourceID": "dox",
      "attributes": {},
      "targetID": "commander",
      "size": 1
    },
    {
      "sourceID": "dox",
      "attributes": {},
      "targetID": "github-flavored-markdown",
      "size": 1
    },
    {
      "sourceID": "node-sass",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "node-sass",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "node-sass",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "gm",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "gm",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "node-log",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "node-log",
      "attributes": {},
      "targetID": "coffee-script",
      "size": 1
    },
    {
      "sourceID": "component-builder",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "component-builder",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "component-builder",
      "attributes": {},
      "targetID": "fs-extra",
      "size": 1
    },
    {
      "sourceID": "component-builder",
      "attributes": {},
      "targetID": "batch",
      "size": 1
    },
    {
      "sourceID": "hyperquest",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "hyperquest",
      "attributes": {},
      "targetID": "duplexer",
      "size": 1
    },
    {
      "sourceID": "graphviz",
      "attributes": {},
      "targetID": "temp",
      "size": 1
    },
    {
      "sourceID": "levelup",
      "attributes": {},
      "targetID": "semver",
      "size": 1
    },
    {
      "sourceID": "levelup",
      "attributes": {},
      "targetID": "xtend",
      "size": 1
    },
    {
      "sourceID": "levelup",
      "attributes": {},
      "targetID": "concat-stream",
      "size": 1
    },
    {
      "sourceID": "msgpack-js",
      "attributes": {},
      "targetID": "bops",
      "size": 1
    },
    {
      "sourceID": "mincer",
      "attributes": {},
      "targetID": "lodash",
      "size": 1
    },
    {
      "sourceID": "mincer",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "mincer",
      "attributes": {},
      "targetID": "argparse",
      "size": 1
    },
    {
      "sourceID": "mincer",
      "attributes": {},
      "targetID": "fs-tools",
      "size": 1
    },
    {
      "sourceID": "riak-js",
      "attributes": {},
      "targetID": "xml",
      "size": 1
    },
    {
      "sourceID": "contextify",
      "attributes": {},
      "targetID": "bindings",
      "size": 1
    },
    {
      "sourceID": "level-sublevel",
      "attributes": {},
      "targetID": "xtend",
      "size": 1
    },
    {
      "sourceID": "tape",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "tape",
      "attributes": {},
      "targetID": "deep-equal",
      "size": 1
    },
    {
      "sourceID": "tape",
      "attributes": {},
      "targetID": "jsonify",
      "size": 1
    },
    {
      "sourceID": "elementtree",
      "attributes": {},
      "targetID": "sax",
      "size": 1
    },
    {
      "sourceID": "ftp",
      "attributes": {},
      "targetID": "xregexp",
      "size": 1
    },
    {
      "sourceID": "node-inspector",
      "attributes": {},
      "targetID": "socket.io",
      "size": 1
    },
    {
      "sourceID": "node-inspector",
      "attributes": {},
      "targetID": "connect",
      "size": 1
    },
    {
      "sourceID": "node-inspector",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "portscanner",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "burrito",
      "attributes": {},
      "targetID": "uglify-js",
      "size": 1
    },
    {
      "sourceID": "burrito",
      "attributes": {},
      "targetID": "traverse",
      "size": 1
    },
    {
      "sourceID": "trumpet",
      "attributes": {},
      "targetID": "inherits",
      "size": 1
    },
    {
      "sourceID": "trumpet",
      "attributes": {},
      "targetID": "sax",
      "size": 1
    },
    {
      "sourceID": "trumpet",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "trumpet",
      "attributes": {},
      "targetID": "duplexer",
      "size": 1
    },
    {
      "sourceID": "trumpet",
      "attributes": {},
      "targetID": "buffers",
      "size": 1
    },
    {
      "sourceID": "trumpet",
      "attributes": {},
      "targetID": "ent",
      "size": 1
    },
    {
      "sourceID": "ref",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "ref",
      "attributes": {},
      "targetID": "bindings",
      "size": 1
    },
    {
      "sourceID": "ref-struct",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "ref-struct",
      "attributes": {},
      "targetID": "ref",
      "size": 1
    },
    {
      "sourceID": "ffi",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "ffi",
      "attributes": {},
      "targetID": "bindings",
      "size": 1
    },
    {
      "sourceID": "ffi",
      "attributes": {},
      "targetID": "ref",
      "size": 1
    },
    {
      "sourceID": "ffi",
      "attributes": {},
      "targetID": "ref-struct",
      "size": 1
    },
    {
      "sourceID": "scuttlebutt",
      "attributes": {},
      "targetID": "duplex",
      "size": 1
    },
    {
      "sourceID": "scuttlebutt",
      "attributes": {},
      "targetID": "monotonic-timestamp",
      "size": 1
    },
    {
      "sourceID": "form-data",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "form-data",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "js2coffee",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "js2coffee",
      "attributes": {},
      "targetID": "coffee-script",
      "size": 1
    },
    {
      "sourceID": "js2coffee",
      "attributes": {},
      "targetID": "file",
      "size": 1
    },
    {
      "sourceID": "css",
      "attributes": {},
      "targetID": "css-parse",
      "size": 1
    },
    {
      "sourceID": "js-beautify",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "js-beautify",
      "attributes": {},
      "targetID": "nopt",
      "size": 1
    },
    {
      "sourceID": "q-io",
      "attributes": {},
      "targetID": "q",
      "size": 1
    },
    {
      "sourceID": "q-io",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "q-io",
      "attributes": {},
      "targetID": "qs",
      "size": 1
    },
    {
      "sourceID": "q-io",
      "attributes": {},
      "targetID": "collections",
      "size": 1
    },
    {
      "sourceID": "JSONPath",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "mochiscript",
      "attributes": {},
      "targetID": "watch",
      "size": 1
    },
    {
      "sourceID": "leveldown",
      "attributes": {},
      "targetID": "bindings",
      "size": 1
    },
    {
      "sourceID": "sync",
      "attributes": {},
      "targetID": "fibers",
      "size": 1
    },
    {
      "sourceID": "extended",
      "attributes": {},
      "targetID": "grunt",
      "size": 1
    },
    {
      "sourceID": "is-extended",
      "attributes": {},
      "targetID": "extended",
      "size": 1
    },
    {
      "sourceID": "array-extended",
      "attributes": {},
      "targetID": "grunt",
      "size": 1
    },
    {
      "sourceID": "array-extended",
      "attributes": {},
      "targetID": "grunt-contrib-jshint",
      "size": 1
    },
    {
      "sourceID": "array-extended",
      "attributes": {},
      "targetID": "grunt-contrib-uglify",
      "size": 1
    },
    {
      "sourceID": "array-extended",
      "attributes": {},
      "targetID": "extended",
      "size": 1
    },
    {
      "sourceID": "array-extended",
      "attributes": {},
      "targetID": "is-extended",
      "size": 1
    },
    {
      "sourceID": "stream-combiner",
      "attributes": {},
      "targetID": "duplexer",
      "size": 1
    },
    {
      "sourceID": "uglify-js2",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "uglify-js2",
      "attributes": {},
      "targetID": "source-map",
      "size": 1
    },
    {
      "sourceID": "upnode",
      "attributes": {},
      "targetID": "dnode",
      "size": 1
    },
    {
      "sourceID": "fstream-ignore",
      "attributes": {},
      "targetID": "minimatch",
      "size": 1
    },
    {
      "sourceID": "fstream-ignore",
      "attributes": {},
      "targetID": "fstream",
      "size": 1
    },
    {
      "sourceID": "fstream-ignore",
      "attributes": {},
      "targetID": "inherits",
      "size": 1
    },
    {
      "sourceID": "smoosh",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "smoosh",
      "attributes": {},
      "targetID": "rimraf",
      "size": 1
    },
    {
      "sourceID": "smoosh",
      "attributes": {},
      "targetID": "uglify-js",
      "size": 1
    },
    {
      "sourceID": "smoosh",
      "attributes": {},
      "targetID": "jshint",
      "size": 1
    },
    {
      "sourceID": "smoosh",
      "attributes": {},
      "targetID": "sqwish",
      "size": 1
    },
    {
      "sourceID": "yui",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "difflet",
      "attributes": {},
      "targetID": "charm",
      "size": 1
    },
    {
      "sourceID": "difflet",
      "attributes": {},
      "targetID": "traverse",
      "size": 1
    },
    {
      "sourceID": "shoe",
      "attributes": {},
      "targetID": "sockjs",
      "size": 1
    },
    {
      "sourceID": "level",
      "attributes": {},
      "targetID": "levelup",
      "size": 1
    },
    {
      "sourceID": "level",
      "attributes": {},
      "targetID": "leveldown",
      "size": 1
    },
    {
      "sourceID": "markdown-js",
      "attributes": {},
      "targetID": "test",
      "size": 1
    },
    {
      "sourceID": "yamljs",
      "attributes": {},
      "targetID": "glob",
      "size": 1
    },
    {
      "sourceID": "yamljs",
      "attributes": {},
      "targetID": "argparse",
      "size": 1
    },
    {
      "sourceID": "passport-http",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "passport-http",
      "attributes": {},
      "targetID": "passport",
      "size": 1
    },
    {
      "sourceID": "docparse-config",
      "attributes": {},
      "targetID": "temp",
      "size": 1
    },
    {
      "sourceID": "docparse-config",
      "attributes": {},
      "targetID": "nconf",
      "size": 1
    },
    {
      "sourceID": "seaport",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "seaport",
      "attributes": {},
      "targetID": "semver",
      "size": 1
    },
    {
      "sourceID": "seaport",
      "attributes": {},
      "targetID": "inherits",
      "size": 1
    },
    {
      "sourceID": "seaport",
      "attributes": {},
      "targetID": "through",
      "size": 1
    },
    {
      "sourceID": "seaport",
      "attributes": {},
      "targetID": "crdt",
      "size": 1
    },
    {
      "sourceID": "loggly-console-logger",
      "attributes": {},
      "targetID": "winston",
      "size": 1
    },
    {
      "sourceID": "apn",
      "attributes": {},
      "targetID": "q",
      "size": 1
    },
    {
      "sourceID": "passport-google-oauth",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "passport-google-oauth",
      "attributes": {},
      "targetID": "passport-oauth",
      "size": 1
    },
    {
      "sourceID": "forEachAsync",
      "attributes": {},
      "targetID": "sequence",
      "size": 1
    },
    {
      "sourceID": "yuidocjs",
      "attributes": {},
      "targetID": "express",
      "size": 1
    },
    {
      "sourceID": "yuidocjs",
      "attributes": {},
      "targetID": "graceful-fs",
      "size": 1
    },
    {
      "sourceID": "yuidocjs",
      "attributes": {},
      "targetID": "minimatch",
      "size": 1
    },
    {
      "sourceID": "yuidocjs",
      "attributes": {},
      "targetID": "rimraf",
      "size": 1
    },
    {
      "sourceID": "yuidocjs",
      "attributes": {},
      "targetID": "node-markdown",
      "size": 1
    },
    {
      "sourceID": "yuidocjs",
      "attributes": {},
      "targetID": "yui",
      "size": 1
    },
    {
      "sourceID": "mongoose-types",
      "attributes": {},
      "targetID": "mongoose",
      "size": 1
    },
    {
      "sourceID": "funargs",
      "attributes": {},
      "targetID": "eyes",
      "size": 1
    },
    {
      "sourceID": "ender-bootstrap-base",
      "attributes": {},
      "targetID": "bean",
      "size": 1
    },
    {
      "sourceID": "ender-bootstrap-base",
      "attributes": {},
      "targetID": "bonzo",
      "size": 1
    },
    {
      "sourceID": "ender-bootstrap-base",
      "attributes": {},
      "targetID": "domready",
      "size": 1
    },
    {
      "sourceID": "ender-bootstrap-transition",
      "attributes": {},
      "targetID": "ender-bootstrap-base",
      "size": 1
    },
    {
      "sourceID": "engine.io-client",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "engine.io-client",
      "attributes": {},
      "targetID": "ws",
      "size": 1
    },
    {
      "sourceID": "engine.io-client",
      "attributes": {},
      "targetID": "xmlhttprequest",
      "size": 1
    },
    {
      "sourceID": "ldapjs",
      "attributes": {},
      "targetID": "nopt",
      "size": 1
    },
    {
      "sourceID": "ldapjs",
      "attributes": {},
      "targetID": "bunyan",
      "size": 1
    },
    {
      "sourceID": "ldapjs",
      "attributes": {},
      "targetID": "buffertools",
      "size": 1
    },
    {
      "sourceID": "ldapjs",
      "attributes": {},
      "targetID": "assert-plus",
      "size": 1
    },
    {
      "sourceID": "ldapjs",
      "attributes": {},
      "targetID": "dtrace-provider",
      "size": 1
    },
    {
      "sourceID": "LiveScript",
      "attributes": {},
      "targetID": "prelude-ls",
      "size": 1
    },
    {
      "sourceID": "reconnect",
      "attributes": {},
      "targetID": "backoff",
      "size": 1
    },
    {
      "sourceID": "reconnect",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "reconnect",
      "attributes": {},
      "targetID": "shoe",
      "size": 1
    },
    {
      "sourceID": "exec-sync",
      "attributes": {},
      "targetID": "ffi",
      "size": 1
    },
    {
      "sourceID": "passport-facebook",
      "attributes": {},
      "targetID": "pkginfo",
      "size": 1
    },
    {
      "sourceID": "passport-facebook",
      "attributes": {},
      "targetID": "passport-oauth",
      "size": 1
    },
    {
      "sourceID": "update-notifier",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "update-notifier",
      "attributes": {},
      "targetID": "semver",
      "size": 1
    },
    {
      "sourceID": "update-notifier",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "fire",
      "attributes": {},
      "targetID": "nopt",
      "size": 1
    },
    {
      "sourceID": "latest",
      "attributes": {},
      "targetID": "npm",
      "size": 1
    },
    {
      "sourceID": "yeoman-generator",
      "attributes": {},
      "targetID": "cheerio",
      "size": 1
    },
    {
      "sourceID": "yeoman-generator",
      "attributes": {},
      "targetID": "lodash",
      "size": 1
    },
    {
      "sourceID": "yeoman-generator",
      "attributes": {},
      "targetID": "mkdirp",
      "size": 1
    },
    {
      "sourceID": "yeoman-generator",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "yeoman-generator",
      "attributes": {},
      "targetID": "request",
      "size": 1
    },
    {
      "sourceID": "yeoman-generator",
      "attributes": {},
      "targetID": "underscore.string",
      "size": 1
    },
    {
      "sourceID": "yeoman-generator",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "yeoman-generator",
      "attributes": {},
      "targetID": "nopt",
      "size": 1
    },
    {
      "sourceID": "yeoman-generator",
      "attributes": {},
      "targetID": "rimraf",
      "size": 1
    },
    {
      "sourceID": "yeoman-generator",
      "attributes": {},
      "targetID": "tar",
      "size": 1
    },
    {
      "sourceID": "yeoman-generator",
      "attributes": {},
      "targetID": "glob",
      "size": 1
    },
    {
      "sourceID": "yeoman-generator",
      "attributes": {},
      "targetID": "debug",
      "size": 1
    },
    {
      "sourceID": "yeoman-generator",
      "attributes": {},
      "targetID": "cli-table",
      "size": 1
    },
    {
      "sourceID": "yeoman-generator",
      "attributes": {},
      "targetID": "diff",
      "size": 1
    },
    {
      "sourceID": "jsftp",
      "attributes": {},
      "targetID": "async",
      "size": 1
    },
    {
      "sourceID": "jsftp",
      "attributes": {},
      "targetID": "event-stream",
      "size": 1
    },
    {
      "sourceID": "xmlrpc",
      "attributes": {},
      "targetID": "sax",
      "size": 1
    },
    {
      "sourceID": "xmlrpc",
      "attributes": {},
      "targetID": "xmlbuilder",
      "size": 1
    },
    {
      "sourceID": "twit",
      "attributes": {},
      "targetID": "oauth",
      "size": 1
    },
    {
      "sourceID": "grunt-contrib-cssmin",
      "attributes": {},
      "targetID": "clean-css",
      "size": 1
    },
    {
      "sourceID": "grunt-contrib-cssmin",
      "attributes": {},
      "targetID": "grunt-lib-contrib",
      "size": 1
    },
    {
      "sourceID": "grunt-contrib-nodeunit",
      "attributes": {},
      "targetID": "nodeunit",
      "size": 1
    },
    {
      "sourceID": "grunt-lib-phantomjs",
      "attributes": {},
      "targetID": "semver",
      "size": 1
    },
    {
      "sourceID": "grunt-lib-phantomjs",
      "attributes": {},
      "targetID": "eventemitter2",
      "size": 1
    },
    {
      "sourceID": "grunt-lib-phantomjs",
      "attributes": {},
      "targetID": "temporary",
      "size": 1
    },
    {
      "sourceID": "grunt-lib-phantomjs",
      "attributes": {},
      "targetID": "phantomjs",
      "size": 1
    },
    {
      "sourceID": "joose",
      "attributes": {},
      "targetID": "temp",
      "size": 1
    },
    {
      "sourceID": "joose",
      "attributes": {},
      "targetID": "optimist",
      "size": 1
    },
    {
      "sourceID": "joose",
      "attributes": {},
      "targetID": "detective",
      "size": 1
    },
    {
      "sourceID": "iwebpp.io",
      "attributes": {},
      "targetID": "node-uuid",
      "size": 1
    },
    {
      "sourceID": "iwebpp.io",
      "attributes": {},
      "targetID": "msgpack-js",
      "size": 1
    },
    {
      "sourceID": "iwebpp.io",
      "attributes": {},
      "targetID": "siphash",
      "size": 1
    },
    {
      "sourceID": "jsgui-lang-essentials",
      "attributes": {},
      "targetID": "amdefine",
      "size": 1
    },
    {
      "sourceID": "logmimosa",
      "attributes": {},
      "targetID": "growl",
      "size": 1
    },
    {
      "sourceID": "logmimosa",
      "attributes": {},
      "targetID": "date-utils",
      "size": 1
    },
    {
      "sourceID": "logmimosa",
      "attributes": {},
      "targetID": "ansi-color",
      "size": 1
    },
    {
      "sourceID": "node-document-storage",
      "attributes": {},
      "targetID": "colors",
      "size": 1
    },
    {
      "sourceID": "node-document-storage",
      "attributes": {},
      "targetID": "sugar",
      "size": 1
    },
    {
      "sourceID": "node-document-storage",
      "attributes": {},
      "targetID": "chai",
      "size": 1
    },
    {
      "sourceID": "node-document-storage",
      "attributes": {},
      "targetID": "longjohn",
      "size": 1
    },
    {
      "sourceID": "node-document-storage",
      "attributes": {},
      "targetID": "sync",
      "size": 1
    },
    {
      "sourceID": "node-document-storage",
      "attributes": {},
      "targetID": "funargs",
      "size": 1
    },
    {
      "sourceID": "noflo",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "noflo",
      "attributes": {},
      "targetID": "npmlog",
      "size": 1
    },
    {
      "sourceID": "noflo",
      "attributes": {},
      "targetID": "coffee-script",
      "size": 1
    },
    {
      "sourceID": "noflo",
      "attributes": {},
      "targetID": "cli-color",
      "size": 1
    },
    {
      "sourceID": "noflo",
      "attributes": {},
      "targetID": "cli",
      "size": 1
    },
    {
      "sourceID": "punch",
      "attributes": {},
      "targetID": "underscore",
      "size": 1
    },
    {
      "sourceID": "punch",
      "attributes": {},
      "targetID": "connect",
      "size": 1
    },
    {
      "sourceID": "punch",
      "attributes": {},
      "targetID": "mustache",
      "size": 1
    },
    {
      "sourceID": "punch",
      "attributes": {},
      "targetID": "mime",
      "size": 1
    },
    {
      "sourceID": "punch",
      "attributes": {},
      "targetID": "fstream",
      "size": 1
    },
    {
      "sourceID": "punch",
      "attributes": {},
      "targetID": "coffee-script",
      "size": 1
    },
    {
      "sourceID": "punch",
      "attributes": {},
      "targetID": "less",
      "size": 1
    },
    {
      "sourceID": "punch",
      "attributes": {},
      "targetID": "uglify-js",
      "size": 1
    },
    {
      "sourceID": "punch",
      "attributes": {},
      "targetID": "knox",
      "size": 1
    },
    {
      "sourceID": "punch",
      "attributes": {},
      "targetID": "marked",
      "size": 1
    },
    {
      "sourceID": "punch",
      "attributes": {},
      "targetID": "fresh",
      "size": 1
    },
    {
      "sourceID": "punch",
      "attributes": {},
      "targetID": "cssmin",
      "size": 1
    },
    {
      "sourceID": "joosex-namespace-depended",
      "attributes": {},
      "targetID": "joose",
      "size": 1
    },
    {
      "sourceID": "sourcemint-util-js",
      "attributes": {},
      "targetID": "q",
      "size": 1
    },
    {
      "sourceID": "sourcemint-util-js",
      "attributes": {},
      "targetID": "glob",
      "size": 1
    },
    {
      "sourceID": "sourcemint-util-js",
      "attributes": {},
      "targetID": "wrench",
      "size": 1
    },
    {
      "sourceID": "sourcemint-util-js",
      "attributes": {},
      "targetID": "tunnel",
      "size": 1
    },
    {
      "sourceID": "tower-directive",
      "attributes": {},
      "targetID": "tower-emitter",
      "size": 1
    },
    {
      "sourceID": "voxel",
      "attributes": {},
      "targetID": "inherits",
      "size": 1
    }
  ]
};
myChart.hideLoading();
    myChart.setOption(
      (option = {
        title: {
          text: 'NPM Dependencies'
        },
        animationDurationUpdate: 1500,
        animationEasingUpdate: 'quinticInOut',
        series: [
          {
            type: 'graph',
            layout: 'none',
            // progressiveThreshold: 700,
            data: json.nodes.map(function (node) {
              return {
                x: node.x,
                y: node.y,
                id: node.id,
                name: node.label,
                symbolSize: node.size,
                itemStyle: {
                  color: node.color
                }
              };
            }),
            edges: json.edges.map(function (edge) {
              return {
                source: edge.sourceID,
                target: edge.targetID
              };
            }),
            emphasis: {
              focus: 'adjacency',
              label: {
                position: 'right',
                show: true
              }
            },
            roam: true,
            roamTrigger: 'global',
            lineStyle: {
              width: 0.5,
              curveness: 0.3,
              opacity: 0.7
            }
          }
        ],
        thumbnail: {
          width: '20%',
          height: '20%',
          windowStyle: {
            color: 'rgba(140, 212, 250, 0.5)',
            borderColor: 'rgba(30, 64, 175, 0.7)',
            opacity: 1
          }
        }
      }),
      true
    );

    // ... (941 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
      ]
```
