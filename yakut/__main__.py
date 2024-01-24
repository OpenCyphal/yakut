# Copyright (c) 2020 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

if __name__ == "__main__":
    from warnings import filterwarnings

    filterwarnings("ignore")  # Warnings are meant for developers and should not be shown to users.

    from yakut import main

    main()  # pylint: disable=no-value-for-parameter
