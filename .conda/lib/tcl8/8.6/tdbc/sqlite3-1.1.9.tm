# tdbcsqlite3.tcl --
#
#    SQLite3 database driver for TDBC
#
# Copyright (c) 2008 by Kevin B. Kenny.
# See the file "license.terms" for information on usage and redistribution
# of this file, and for a DISCLAIMER OF ALL WARRANTIES.
#
# RCS: @(#) $Id: tdbcodbc.tcl,v 1.47 2008/02/27 02:08:27 kennykb Exp $
#
#------------------------------------------------------------------------------

package require tdbc
package require sqlite3

package provide tdbc::sqlite3 1.1.9

namespace eval tdbc::sqlite3 {
    namespace export connection
    variable script [info script]

    proc build-info args {
	if {[llength $args] > 0} {
	    if {[llength $args] > 1} {
		return -code error "wrong # args: should be \"[lrange [info level 0] 0 end-[llength $args]]\""
	    }
	    switch -exact -- [lindex $args 0] {
		commit {}
		compiler {return none}
		patchlevel {return [package provide tdbc::sqlite3]}
		version {return [join [lrange [split [package provide tdbc::sqlite3] .] 0 1] .]}
		default {return 0}
	    }
	}
	variable script
	set id unknown
	catch {
	    set f [open [file rootname $script].uuid]
	    set id [string trim [read $f]]
	    close $f
	}
	if {[llength $args] > 0} {
	    return $id
	} else {
	    return [package provide tdbc::sqlite3]+$id
	}
    }
}

#------------------------------------------------------------------------------
#
# tdbc::sqlite3::connection --
#
#	Class representing a SQLite3 database connection
#
#------------------------------------------------------------------------------

::oo::class create ::tdbc::sqlite3::connection {

    superclass ::tdbc::connection

    variable timeout
    variable keepcase

    # The constructor accepts a database name and opens the database.

    constructor {databaseName args} {
	set timeout 0
	set keepcase 0
	if {[llength $args] % 2 != 0} {
	    set cmd [lrange [info level 0] 0 end-[llength $args]]
	    return -code error \
		-errorcode {TDBC GENERAL_ERROR HY000 SQLITE3 WRONGNUMARGS} \
		"wrong # args, should be \"$cmd ?-option value?...\""
	}
	next
	sqlite3 [namespace current]::db $databaseName
	if {[llength $args] > 0} {
	    my configure {*}$args
	}
	db nullvalue \ufffd
    }

    # The 'statementCreate' method forwards to the constructor of the
    # statement class

    forward statementCreate ::tdbc::sqlite3::statement create

    # The 'configure' method queries and sets options to the database

    method configure args {
	if {[llength $args] == 0} {

	    # Query all configuration options

	    set result {-encoding utf-8}
	    lappend result -isolation
	    if {[db onecolumn {PRAGMA read_uncommitted}]} {
		lappend result readuncommitted
	    } else {
		lappend result serializable
	    }
	    lappend result -keepcase $keepcase
	    lappend result -readonly 0
	    lappend result -timeout $timeout
	    return $result

	} elseif {[llength $args] == 1} {

	    # Query a single option

	    set option [lindex $args 0]
	    if {[catch {::tcl::prefix match -message "option" {
		-encoding -isolation -keepcase -readonly -timeout
	    } $option} opt]} {
		return -code error \
			-errorcode [list TDBC GENERAL_ERROR HY000 SQLITE3 \
					BADOPTION $option] $opt
	    }
	    switch -exact -- $opt {
 		-encoding {
		    return utf-8
		}
		-isolation {
		    if {[db onecolumn {PRAGMA read_uncommitted}]} {
			return readuncommitted
		    } else {
			return serializable
		    }
		}
		-keepcase {
		    return $keepcase
		}
		-readonly {
		    return 0
		}
		-timeout {
		    return $timeout
		}
	    }

	} elseif {[llength $args] % 2 != 0} {

	    # Syntax error

	    set cmd [lrange [info level 0] 0 end-[llength $args]]
	    return -code error \
		-errorcode [list TDBC GENERAL_ERROR HY000 \
				SQLITE3 WRONGNUMARGS] \
		"wrong # args, should be \" $cmd ?-option value?...\""
	}

	# Set one or more options

	foreach {option value} $args {
	    if {[catch {::tcl::prefix match -message "option" {
		-encoding -isolation -keepcase -readonly -timeout
	    } $option} opt]} {
		return -code error \
			-errorcode [list TDBC GENERAL_ERROR HY000 SQLITE3 \
					BADOPTION $option] $opt
	    }

	    switch -exact -- $opt {
		-encoding {
		    if {$value ne {utf-8}} {
			return -code error \
			    -errorcode [list TDBC FEATURE_NOT_SUPPORTED 0A000 \
					    SQLITE3 ENCODING] \
			    "-encoding not supported. SQLite3 is always\
			     Unicode."
		    }
		}
		-isolation {
		    if {[catch {::tcl::prefix match -message "isolation level" {
			readuncommitted readcommitted repeatableread
			serializable readonly
		    } $value} val]} {
			return -code error \
			    -errorcode [list TDBC GENERAL_ERROR HY000 \
					    SQLITE3 BADISOLATION $value] \
			    $val
		    }
		    switch -exact -- $val {
			readuncommitted {
			    db eval {PRAGMA read_uncommitted = 1}
			}
			readcommitted -
			repeatableread -
			serializable -
			readonly {
			    db eval {PRAGMA read_uncommitted = 0}
			}
		    }
		}
		-keepcase {
		    if {![string is boolean -strict $value]} {
			return -code error \
			    -errorcode [list TDBC DATA_EXCEPTION 22018 \
					    SQLITE3 $value] \
			    "expected boolean but got \"$value\""
		    }
		    # Normalize boolean value to 0/1
		    set keepcase [expr {bool($value)}]
		}
		-readonly {
		    if {$value} {
			return -code error \
			    -errorcode [list TDBC FEATURE_NOT_SUPPORTED 0A000 \
					    SQLITE3 READONLY] \
			    "SQLite3's Tcl API does not support read-only\
			     access"
		    }
		}
		-timeout {
		    if {![string is integer -strict $value]} {
			return -code error \
			    -errorcode [list TDBC DATA_EXCEPTION 22018 \
					    SQLITE3 $value] \
			    "expected integer but got \"$value\""
		    }
		    db timeout $value
		    set timeout $value
		}
	    }
	}
	return
    }

    # The 'tables' method introspects on the tables in the database.

    method tables {{pattern %}} {
	set retval {}
	my foreach row {
	    SELECT * from sqlite_master
	    WHERE type IN ('table', 'view')
	    AND name LIKE :pattern
	} {
	    if {!$keepcase} {
		dict set row name [string tolower [dict get $row name]]
	    }
	    dict set retval [dict get $row name] $row
	}
	return $retval
    }

    # The 'columns' method introspects on columns of a table.

    method columns {table {pattern %}} {
	regsub -all ' $table '' table
	set retval {}
	set pattern [string map [list \
				     * {[*]} \
				     ? {[?]} \
				     \[ \\\[ \
				     \] \\\[ \
				     _ ? \
				     % *] [string tolower $pattern]]
	my foreach origrow "PRAGMA table_info('$table')" {
	    set row {}
	    dict for {key value} $origrow {
		dict set row [string tolower $key] $value
	    }
	    if {!$keepcase} {
		dict set row name [string tolower [dict get $row name]]
	    }
	    if {![string match $pattern \
		      [string tolower [dict get $row name]]]} {
		continue
	    }
	    switch -regexp -matchvar info [dict get $row type] {
		{^(.+)\(\s*([[:digit:]]+)\s*,\s*([[:digit:]]+)\s*\)\s*$} {
		    dict set row type \
			    [string trim [string tolower [lindex $info 1]]]
		    dict set row precision [lindex $info 2]
		    dict set row scale [lindex $info 3]
		}
		{^(.+)\(\s*([[:digit:]]+)\s*\)\s*$} {
		    dict set row type [string tolower [lindex $info 1]]
		    dict set row precision [lindex $info 2]
		    dict set row scale 0
		}
		default {
		    dict set row type [string tolower [dict get $row type]]
		    dict set row precision 0
		    dict set row scale 0
		}
	    }
	    dict set row nullable [expr {![dict get $row notnull]}]
	    dict set retval [dict get $row name] $row
	}
	return $retval
    }

    # The 'primarykeys' method enumerates the primary keys on a table.

    method primarykeys {table} {
	set result {}
	my foreach row "PRAGMA table_info($table)" {
	    if {[dict get $row pk]} {
		lappend result [dict create ordinalPosition \
				    [expr {[dict get $row cid]+1}] \
				    columnName \
				    [dict get $row name]]
	    }
	}
	return $result
    }

    # The 'foreignkeys' method enumerates the foreign keys that are
    # declared in a table or that refer to a given table.

    method foreignkeys {args} {

	variable ::tdbc::generalError

	# Check arguments

	set argdict {}
	if {[llength $args] % 2 != 0} {
	    set errorcode $generalError
	    lappend errorcode wrongNumArgs
	    return -code error -errorcode $errorcode \
		"wrong # args: should be [lrange [info level 0] 0 1]\
		 ?-option value?..."
	}
	foreach {key value} $args {
	    if {$key ni {-primary -foreign}} {
		set errorcode $generalError
		lappend errorcode badOption
		return -code error -errorcode $errorcode \
		    "bad option \"$key\", must be -primary or -foreign"
	    }
	    set key [string range $key 1 end]
	    if {[dict exists $argdict $key]} {
		set errorcode $generalError
		lappend errorcode dupOption
		return -code error -errorcode $errorcode \
		    "duplicate option \"$key\" supplied"
	    }
	    dict set argdict $key $value
	}

	# If we know the table with the foreign key, search just its
	# foreign keys. Otherwise, iterate over all the tables in the
	# database.

	if {[dict exists $argdict foreign]} {
	    return [my ForeignKeysForTable [dict get $argdict foreign] \
			$argdict]
	} else {
	    set result {}
	    foreach foreignTable [dict keys [my tables]] {
		lappend result {*}[my ForeignKeysForTable \
				       $foreignTable $argdict]
	    }
	    return $result
	}

    }

    # The private ForeignKeysForTable method enumerates the foreign keys
    # in a specific table.
    #
    # Parameters:
    #
    #	foreignTable - Name of the table containing foreign keys.
    #   argdict - Dictionary that may or may not contain a key,
    #             'primary', whose value is the name of a table that
    #             must hold the primary key corresponding to the foreign
    #             key. If the 'primary' key is absent, all tables are
    #             candidates.
    # Results:
    #
    # 	Returns the list of foreign keys that meed the specified
    # 	conditions, as a list of dictionaries, each containing the
    # 	keys, foreignConstraintName, foreignTable, foreignColumn,
    # 	primaryTable, primaryColumn, and ordinalPosition.  Note that the
    #   foreign constraint name is constructed arbitrarily, since SQLite3
    #   does not report this information.

    method ForeignKeysForTable {foreignTable argdict} {

	set result {}
	set n 0

	# Go through the foreign keys in the given table, looking for
	# ones that refer to the primary table (if one is given), or
	# for any primary keys if none is given.
	my foreach row "PRAGMA foreign_key_list($foreignTable)" {
	    if {(![dict exists $argdict primary])
		|| ([string tolower [dict get $row table]]
		    eq [string tolower [dict get $argdict primary]])} {

		# Construct a dictionary for each key, translating
		# SQLite names to TDBC ones and converting sequence
		# numbers to 1-based indexing.

		set rrow [dict create foreignTable $foreignTable \
			      foreignConstraintName \
			      ?$foreignTable?[dict get $row id]]
		if {[dict exists $row seq]} {
		    dict set rrow ordinalPosition \
			[expr {1 + [dict get $row seq]}]
		}
		foreach {to from} {
		    foreignColumn from
		    primaryTable table
		    primaryColumn to
		    deleteAction on_delete
		    updateAction on_update
		} {
		    if {[dict exists $row $from]} {
			dict set rrow $to [dict get $row $from]
		    }
		}

		# Add the newly-constucted dictionary to the result list

		lappend result $rrow
	    }
	}

	return $result
    }

    # The 'preparecall' method prepares a call to a stored procedure.
    # SQLite3 does not have stored procedures, since it's an in-process
    # server.

    method preparecall {call} {
	return -code error \
	    -errorcode [list TDBC FEATURE_NOT_SUPPORTED 0A000 \
			    SQLITE3 PREPARECALL] \
	    {SQLite3 does not support stored procedures}
    }

    # The 'begintransaction' method launches a database transaction

    method begintransaction {} {
	db eval {BEGIN TRANSACTION}
    }

    # The 'commit' method commits a database transaction

    method commit {} {
	db eval {COMMIT}
    }

    # The 'rollback' method abandons a database transaction

    method rollback {} {
	db eval {ROLLBACK}
    }

    # The 'transaction' method executes a script as a single transaction.
    # We override the 'transaction' method of the base class, since SQLite3
    # has a faster implementation of the same thing. (The base class's generic
    # method should also work.)
    # (Don't overload the base class method, because 'break', 'continue'
    # and 'return' in the transaction body don't work!)

    #method transaction {script} {
    #	uplevel 1 [list {*}[namespace code db] transaction $script]
    #}

    method prepare {sqlCode} {
	set result [next $sqlCode]
	return $result
    }

    method getDBhandle {} {
	return [namespace which db]
    }
}

#------------------------------------------------------------------------------
#
# tdbc::sqlite3::statement --
#
#	Class representing a statement to execute against a SQLite3 database
#
#------------------------------------------------------------------------------

::oo::class create ::tdbc::sqlite3::statement {

    superclass ::tdbc::statement

    variable Params db sql

    # The constructor accepts the handle to the connection and the SQL
    # code for the statement to prepare.  All that it does is to parse the
    # statement and store it.  The parse is used to support the
    # 'params' and 'paramtype' methods.

    constructor {connection sqlcode} {
	next
	set Params {}
	set db [$connection getDBhandle]
	set sql $sqlcode
	foreach token [::tdbc::tokenize $sqlcode] {
	    if {[string index $token 0] in {$ : @}} {
		dict set Params [string range $token 1 end] \
		    {type Tcl_Obj precision 0 scale 0 nullable 1 direction in}
	    }
	}
    }

    # The 'resultSetCreate' method relays to the result set constructor

    forward resultSetCreate ::tdbc::sqlite3::resultset create

    # The 'params' method returns descriptions of the parameters accepted
    # by the statement

    method params {} {
	return $Params
    }

    # The 'paramtype' method need do nothing; Sqlite3 uses manifest typing.

    method paramtype args {;}

    method getDBhandle {} {
	return $db
    }

    method getSql {} {
	return $sql
    }

}

#-------------------------------------------------------------------------------
#
# tdbc::sqlite3::resultset --
#
#	Class that represents a SQLlite result set in Tcl
#
#-------------------------------------------------------------------------------

::oo::class create ::tdbc::sqlite3::resultset {

    superclass ::tdbc::resultset

    # The variables of this class all have peculiar names. The reason is
    # that the RunQuery method needs to execute with an activation record
    # that has no local variables whose names could conflict with names
    # in the SQL query. We start the variable names with hyphens because
    # they can't be bind variables.

    variable -set {*}{
	-columns -db -needcolumns -resultArray
	-results -sql -Cursor -RowCount -END
    }

    constructor {statement args} {
	next
	set -db [$statement getDBhandle]
	set -sql [$statement getSql]
	set -columns {}
	set -results {}
	${-db} trace [namespace code {my RecordStatement}]
	if {[llength $args] == 0} {

	    # Variable substitutions are evaluated in caller's context

	    uplevel 1 [list ${-db} eval ${-sql} \
			   [namespace which -variable -resultArray] \
			   [namespace code {my RecordResult}]]

	} elseif {[llength $args] == 1} {

	    # Variable substitutions are in the dictionary at [lindex $args 0].

	    set -paramDict [lindex $args 0]

	    # At this point, the activation record must contain no variables
	    # that might be bound within the query.  All variables at this point
	    # begin with hyphens so that they are syntactically incorrect
	    # as bound variables in SQL.

	    unset args
	    unset statement

	    dict with -paramDict {
		${-db} eval ${-sql} -resultArray {
		    my RecordResult
		}
	    }

	} else {

	    ${-db} trace {}

	    # Too many args

	    return -code error \
		-errorcode [list TDBC GENERAL_ERROR HY000 \
				SQLITE3 WRONGNUMARGS] \
		"wrong # args: should be\
		 [lrange [info level 0] 0 1] statement ?dictionary?"

	}
	${-db} trace {}
	set -Cursor 0
	if {${-Cursor} < [llength ${-results}]
	    && [lindex ${-results} ${-Cursor}] eq {statement}} {
	    incr -Cursor 2
	}
	if {${-Cursor} < [llength ${-results}]
	    && [lindex ${-results} ${-Cursor}] eq {columns}} {
	    incr -Cursor
	    set -columns [lindex ${-results} ${-Cursor}]
	    incr -Cursor
	}
	set -RowCount [${-db} changes]
    }

    # Record the start of a SQL statement

    method RecordStatement {stmt} {
	set -needcolumns 1
	lappend -results statement {}
    }

    # Record one row of results from a query by appending it as a dictionary
    # to the 'results' list.  As a side effect, set 'columns' to a list
    # comprising the names of the columns of the result.

    method RecordResult {} {
	set columns ${-resultArray(*)}
	if {[info exists -needcolumns]} {
	    lappend -results columns $columns
	    unset -needcolumns
	}
	set dict {}
	foreach key $columns {
	    if {[set -resultArray($key)] ne "\ufffd"} {
		dict set dict $key [set -resultArray($key)]
	    }
	}
	lappend -results row $dict
    }

    # Advance to the next result set

    method nextresults {} {
	set have 0
	while {${-Cursor} < [llength ${-results}]} {
	    if {[lindex ${-results} ${-Cursor}] eq {statement}} {
		set have 1
		incr -Cursor 2
		break
	    }
	    incr -Cursor 2
	}
	if {!$have} {
	    set -END {}
	}
	if {${-Cursor} >= [llength ${-results}]} {
	    set -columns {}
	} elseif {[lindex ${-results} ${-Cursor}] eq {columns}} {
	    incr -Cursor
	    set -columns [lindex ${-results} ${-Cursor}]
	    incr -Cursor
	} else {
	    set -columns {}
	}
	return $have
    }

    method getDBhandle {} {
	return ${-db}
    }

    # Return a list of the columns

    method columns {} {
	if {[info exists -END]} {
	    return -code error \
		-errorcode {TDBC GENERAL_ERROR HY010 SQLITE3 FUNCTIONSEQ} \
		"Function sequence error: result set is exhausted."
	}
	return ${-columns}
    }

    # Return the next row of the result set as a list

    method nextlist var {

	upvar 1 $var row

	if {[info exists -END]} {
	    return -code error \
		-errorcode {TDBC GENERAL_ERROR HY010 SQLITE3 FUNCTIONSEQ} \
		"Function sequence error: result set is exhausted."
	}
	if {${-Cursor} >= [llength ${-results}]
	    || [lindex ${-results} ${-Cursor}] ne {row}} {
	    return 0
	} else {
	    set row {}
	    incr -Cursor
	    set d [lindex ${-results} ${-Cursor}]
	    incr -Cursor
	    foreach key ${-columns} {
		if {[dict exists $d $key]} {
		    lappend row [dict get $d $key]
		} else {
		    lappend row {}
		}
	    }
	}
	return 1
    }

    # Return the next row of the result set as a dict

    method nextdict var {

	upvar 1 $var row

	if {[info exists -END]} {
	    return -code error \
		-errorcode {TDBC GENERAL_ERROR HY010 SQLITE3 FUNCTIONSEQ} \
		"Function sequence error: result set is exhausted."
	}
	if {${-Cursor} >= [llength ${-results}]
	    || [lindex ${-results} ${-Cursor}] ne {row}} {
	    return 0
	} else {
	    incr -Cursor
	    set row [lindex ${-results} ${-Cursor}]
	    incr -Cursor
	}
	return 1
    }

    # Return the number of rows affected by a statement

    method rowcount {} {
	if {[info exists -END]} {
	    return -code error \
		-errorcode {TDBC GENERAL_ERROR HY010 SQLITE3 FUNCTIONSEQ} \
		"Function sequence error: result set is exhausted."
	}
	return ${-RowCount}
    }

}
