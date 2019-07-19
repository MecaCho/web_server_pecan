# init project

virtualenv pecan_env
cd pecan_env
source bin/activate
pip install pecan

pecan create web_server_pecan
alias tree="find web_server_pecan/ -print | sed -e 's;[^/]*/;|____;g;s;____|;|;g'"
tree web_server_pecan
|____
||____config.py
||____MANIFEST.in
||____public
|||____css
||||____style.css
|||____images
||||____logo.png
||____setup.cfg
||____setup.py
||____web_server_pecan
|||______init__.py
|||______init__.pyc
|||____app.py
|||____controllers
||||______init__.py
||||______init__.pyc
||||____root.py
||||____root.pyc
|||____model
||||______init__.py
||||______init__.pyc
|||____templates
||||____error.html
||||____index.html
||||____layout.html
|||____tests
||||______init__.py
||||____config.py
||||____test_functional.py
||||____test_units.py
||||____test_units.pyc

# running the application

python setup.py develop
pecan serve config.py
```
Starting server in PID 80615
serving on 0.0.0.0:8080, view at http://127.0.0.1:8080
2019-07-19 15:18:08,490 [INFO    ] [pecan.commands.serve][MainThread] "GET / HTTP/1.1" 200 989
2019-07-19 15:21:03,692 [INFO    ] [pecan.commands.serve][MainThread] "GET / HTTP/1.1" 200 989
2019-07-19 15:21:03,838 [INFO    ] [pecan.commands.serve][MainThread] "GET /css/style.css HTTP/1.1" 200 569
2019-07-19 15:21:03,862 [WARNING ] [pecan.commands.serve][MainThread] "GET /javascript/shared.js HTTP/1.1" 404 407
2019-07-19 15:21:03,885 [INFO    ] [pecan.commands.serve][MainThread] "GET /images/logo.png HTTP/1.1" 200 20596
2019-07-19 15:21:04,398 [WARNING ] [pecan.commands.serve][MainThread] "GET /favicon.ico HTTP/1.1" 404 407
```

# running the Tests for the application
python setup.py test -q

# tips

## WSME
web service Made Easy

