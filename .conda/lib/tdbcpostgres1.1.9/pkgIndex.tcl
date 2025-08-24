# Index file to load the TDBC Postgres package.

if {![package vsatisfies [package provide Tcl] 8.6-]} {
    return
}
if {[package vsatisfies [package provide Tcl] 9.0-]} {
    package ifneeded tdbc::postgres 1.1.9 \
	    "[list source -encoding utf-8 [file join $dir tdbcpostgres.tcl]]\;\
	    [list load [file join $dir libtcl9tdbcpostgres1.1.9.so] [string totitle tdbcpostgres]]"
} else {
    package ifneeded tdbc::postgres 1.1.9 \
	    "[list source -encoding utf-8 [file join $dir tdbcpostgres.tcl]]\;\
	    [list load [file join $dir libtdbcpostgres1.1.9.so] [string totitle tdbcpostgres]]"
}
