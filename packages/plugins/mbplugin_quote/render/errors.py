class CanvasTooLarge(ValueError):
    """布局算出的画布超过像素预算, 在分配画布之前抛出"""

    def __init__(self, width: int, height: int, budget: int) -> None:
        super().__init__(f"canvas {width}x{height} exceeds budget of {budget} pixels")
        self.width = width
        self.height = height
        self.budget = budget
