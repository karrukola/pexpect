"""Echo every line read from stdin back with markers, until EOF."""

while True:
    try:
        a = input("<in >")
    except EOFError:
        print("<eof>")
        break
    print("<out>", a, sep="")
