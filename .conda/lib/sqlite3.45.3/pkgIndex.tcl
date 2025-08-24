# -*- tcl -*-
# Tcl package index file, version 1.1
#
# Note sqlite*3* init specifically
#
if {[package vsatisfies [package provide Tcl] 9.0-]} {
    package ifneeded sqlite3 3.45.3 \
	    [list load [file join $dir libtcl9sqlite3.45.3.so] Sqlite3]
} else {
    package ifneeded sqlite3 3.45.3 \
	    [list load [file join $dir libsqlite3.45.3.so] Sqlite3]
}
